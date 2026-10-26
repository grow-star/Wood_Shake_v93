#!/usr/bin/env python3
"""
TRANSITION REPAIR EVENTS (Path B) — additive
============================================
Authority: docs/Wood_Shake_Spec_Amendment_Transition_Repair_Events_v0_1.md

Path A (passive, ≥95% sweep) is UNCHANGED and lives in module2_scope_expansion.
This module adds only what Path B needs:

  1. THE GATE, ENFORCED AT THE DATA LAYER (§2). v91: every row records WHAT IS AT the transition —
     `metal`, one of module2_scope_expansion.TRANSITION_METAL_VALUES. A transition becomes a repair
     event only when metal == EXPOSED and `damaged` is True. The UI gate is not the enforcement point —
     this is. An unknown metal value, `damaged` asserted on anything but EXPOSED (concealed metal cannot
     have been struck by hail), a legacy `exposed` flag that contradicts `metal`, or two rows that
     disagree about one edge are INCOHERENT: the row records nothing and creates no event, whatever the
     payload says. A legacy row (v81-v90 writer, no `metal`) with exposed=True reads as EXPOSED — it
     asserted exposed metal (Joseph 2026-10-25); a legacy row without exposed=True records nothing.

  2. THE BAND GEOMETRY (§3), per CSSB Figure 10:
       UPPER slope: THREE COURSES up-slope from the shared edge, to the TOP of the 3rd course —
                    geometry_core.three_course_extent_ft() = (2 x exposure + length) / 12; 44 in at
                    the 24 in / 10 in defaults (v90, Joseph 2026-10-17; was a fixed 36 in CSSB 914 mm
                    strip). You cannot install the tie-in beneath courses you have not lifted.
       LOWER slope: ONE (1) COURSE down-slope — a course-lap requirement, specified in courses and
                    therefore read off the slope's own course grid (exposure), not in inches.
     The band runs the full edge_total_LF and is carved on BOTH facets sharing the edge.

The DETECTOR IS UNTOUCHED: this module never creates, moves, or re-lengths a transition. It only
consumes an already-detected one (transition_enumerator.confirmed_transitions) that the user SELECTED.
`edge_total_LF` is geometric truth and is never user-edited — which is what structurally kills any
double-count or length ambiguity.
"""

from __future__ import annotations

from typing import List, Mapping, Optional, Sequence

from geometry_core import resolve_shake_measurements, three_course_extent_ft
from module2_scope_expansion import METAL_EXPOSED, METAL_MEMBRANE, TRANSITION_METAL_VALUES
from transition_enumerator import confirmed_transitions, transition_contact_readings

UPPER_BAND_FT = 3.0        # RETIRED v90 — NOT READ. Was the CSSB 914 mm (36 in) strip. The upper band is now
                           # geometry_core.three_course_extent_ft() (Joseph 2026-10-17: top of the 3rd course).
LOWER_BAND_COURSES = 1     # one course down-slope (course-lap requirement)

UPPER = "UPPER"
LOWER = "LOWER"


# ---------------------------------------------------------------------------
# 1. The gate (data layer — the real enforcement point)
# ---------------------------------------------------------------------------
def _validated_row(data: Mapping[str, object]):
    """(metal, damaged) for ONE coherent row, or None when the row records nothing."""
    damaged = data.get("damaged") is True                 # a non-True value is never a damage assertion
    legacy_exposed = data.get("exposed")
    raw = data.get("metal")
    if raw not in (None, ""):
        metal = raw if isinstance(raw, str) else None
        if metal not in TRANSITION_METAL_VALUES:          # exact match — "exposed", "STEEL", 1 ... rejected
            return None
        if legacy_exposed is True and metal != METAL_EXPOSED:
            return None                                   # says exposed AND says something else
        if legacy_exposed is False and metal == METAL_EXPOSED:
            return None
    elif legacy_exposed is True:
        metal = METAL_EXPOSED                             # v81-v90 row: it asserted exposed metal
    else:
        return None                                       # never answered -> nothing recorded
    if damaged and metal != METAL_EXPOSED:
        return None                                       # damage to metal that is concealed / absent / membrane / unknown
    return metal, damaged


def _row_asserts_something(data: Mapping[str, object]) -> bool:
    return data.get("metal") not in (None, "") or data.get("exposed") is True or data.get("damaged") is True


def _transition_facts(confirmed_selection: Mapping[str, object]) -> dict:
    """{edge_id: (metal, damaged)} — the ONE reading of the payload rows that both the gate
    (selected_transition_repairs) and the emission (transition_metal_facts) use.

    A row that asserts something and fails validation is INCOHERENT and poisons its edge: that edge then
    records nothing and creates no event, even if another row for it looks valid. Two coherent rows that
    disagree about one edge poison it the same way. A row that asserts nothing is simply unanswered.
    Order of first appearance is preserved."""
    seen: dict = {}
    bad: set = set()
    for row in (confirmed_selection.get("transition_repairs", ()) or ()):
        data = dict(row) if not isinstance(row, dict) else row
        edge_id = data.get("edge_id")
        if not edge_id:
            continue
        eid = str(edge_id)
        fact = _validated_row(data)
        if fact is None:
            if _row_asserts_something(data):
                bad.add(eid)
            continue
        if eid in seen and seen[eid] != fact:
            bad.add(eid)
            continue
        seen[eid] = fact
    return {k: v for k, v in seen.items() if k not in bad}


def transition_metal_facts(confirmed_selection: Mapping[str, object]) -> dict:
    """{edge_id: metal} for every transition whose material the user recorded (validated). An edge that
    is absent here was never answered — the emission treats that as v90 (Joseph 2026-10-25)."""
    return {eid: fact[0] for eid, fact in _transition_facts(confirmed_selection).items()}


def selected_transition_repairs(confirmed_selection: Mapping[str, object]) -> tuple:
    """Edge ids the user confirmed as repair events.

    BOTH are required (spec §2, v91 shape):
        metal   == EXPOSED -> the flashing is visible metal, not concealed under the courses
        damaged is True    -> that metal has storm damage

    Anything else — any other metal, damaged False, either absent, a non-True value, or an incoherent
    row — yields NO repair event. This is deliberate: asserting damaged transition flashing is a CLAIM
    that goes into a document an adjuster and an appraiser will read, so it cannot be created by
    accident, and it cannot be smuggled in through the payload either. A recorded fact that is NOT a
    damage claim (CONCEALED, NONE, MEMBRANE, UNKNOWN, or EXPOSED undamaged) creates no event; it only
    changes what a transition emits if it fires by Path A.
    """
    return tuple(eid for eid, (metal, damaged) in _transition_facts(confirmed_selection).items()
                 if metal == METAL_EXPOSED and damaged)


def selected_transitions(geom, confirmed_selection) -> list:
    """The DETECTED transitions the user selected. A selection naming an edge the detector did not
    return is ignored — the user can only ever select something the three-condition test found."""
    wanted = set(selected_transition_repairs(confirmed_selection))
    if not wanted:
        return []
    return [t for t in confirmed_transitions(geom) if t.edge_id in wanted]


# ---------------------------------------------------------------------------
# 1b. PATH A — the passive >=95% rule, now actually LIVE (Build 2b)
# ---------------------------------------------------------------------------
CAP_THRESHOLD = 0.95        # same constant module2_scope_expansion uses; the rule is unchanged


def transition_contact_lf(geom, transition, selected_valley_ids) -> float:
    """Affected-area contact along this transition, from OTHER repairs (the selected valleys).

    Read on BOTH facets and the LARGER taken: the flashing is a single continuous piece spanning
    the edge, so if the repair sweeps its full length on either slope, that flashing is torn out.
    (On Yager's L33 this is 100% on V and 0% on P — the metal is still gone.)
    """
    readings = transition_contact_readings(
        geom, transition, selected_valley_ids=[str(v) for v in (selected_valley_ids or ())])
    return max([float(r["contact_LF"]) for r in readings] or [0.0])


def path_a_transitions(geom, confirmed_selection) -> list:
    """Detected transitions the selected repairs sweep to >=95% of edge_total_LF.

    THE BUG THIS FIXES (Build 2b): module2_assembly always built M1Interface(transitions=[]), so the
    >=95% rule — designed, specified and believed live — had NEVER ONCE RUN on a real roof. Yager's
    L33 is swept 100% by the standard confirmed repair and was being silently dropped.

    The rule itself is unchanged; it is simply evaluated now.
    """
    valley_ids = [str(v) for v in (confirmed_selection.get("selected_valley_ids", ()) or ())]
    if not valley_ids:
        return []
    fired = []
    for t in confirmed_transitions(geom):
        if t.edge_total_LF <= 0:
            continue
        if transition_contact_lf(geom, t, valley_ids) >= CAP_THRESHOLD * float(t.edge_total_LF):
            fired.append(t)
    return fired


# ---------------------------------------------------------------------------
# 1c. PATH R — a REPLACED slope carries its transition (v92)
#     (NOT "Path C": module2_assembly already calls the full-slope-replacement scope path "PATH C" (v61).)
# ---------------------------------------------------------------------------
def replaced_face_ids(confirmed_selection: Mapping[str, object]) -> frozenset:
    """The facets marked for full replacement — the same set module2_assembly builds from
    `replaced_facets` (rows are {face_id} mappings, or bare ids as the seam accepts them)."""
    out = set()
    for it in (confirmed_selection.get("replaced_facets", ()) or ()):
        out.add(str(it["face_id"]) if isinstance(it, Mapping) else str(it))
    return frozenset(out)


def path_r_transitions(geom, confirmed_selection) -> list:
    """Detected transitions with AT LEAST ONE facet in `replaced_facets`.

    A slope being torn off takes its transition detail with it, and you cannot install underlayment
    beneath courses you have not lifted. Like Path A the trigger is CONSEQUENTIAL — no damage assertion is
    involved. Reads `replaced_facets` ONLY: a facet cannot be both replaced and repaired (module2_assembly
    enforces that at the data layer), so Path R can never reach a repaired facet through this set.
    Candidates come from confirmed_transitions(geom), the same source path_a_transitions uses."""
    replaced = replaced_face_ids(confirmed_selection)
    if not replaced:
        return []
    return [t for t in confirmed_transitions(geom)
            if str(t.face_a_id) in replaced or str(t.face_b_id) in replaced]


def active_transitions(geom, confirmed_selection) -> list:
    """Every transition that fires, by ANY path, each appearing exactly ONCE.

    Path A (passive):  the repair swept >=95% of it — the flashing was torn out (consequential).
    Path B (active):   the user asserted EXPOSED metal + damaged — the flashing IS the damage (trigger).
    Path R (replaced): one of its facets is fully replaced — the tear-off takes it (consequential, v92).

    De-duplication is structural: keyed by edge_id, so a transition satisfying A, B and R appears ONCE here
    and the assembly builds ONE Transition for it — it can only ever produce one line of each kind.
    """
    by_id = {}
    for t in path_a_transitions(geom, confirmed_selection):
        by_id[t.edge_id] = t
    for t in selected_transitions(geom, confirmed_selection):
        by_id[t.edge_id] = t
    for t in path_r_transitions(geom, confirmed_selection):
        by_id[t.edge_id] = t
    return [by_id[k] for k in sorted(by_id)]


def transition_paths(geom, confirmed_selection) -> dict:
    """{edge_id: frozenset of "A" / "B" / "R"} for every ACTIVE transition — the ONE reading of which
    paths fired, so nothing downstream re-derives membership."""
    a = {t.edge_id for t in path_a_transitions(geom, confirmed_selection)}
    b = {t.edge_id for t in selected_transitions(geom, confirmed_selection)}
    r = {t.edge_id for t in path_r_transitions(geom, confirmed_selection)}
    return {eid: frozenset(p for p, s in (("A", a), ("B", b), ("R", r)) if eid in s)
            for eid in sorted(a | b | r)}


def trigger_token(paths) -> str:
    """The UI token for a set of fired paths. "BOTH" = consequential (A or R) AND asserted (B) — still ONE
    line of each kind; "PATH_A" wins over "PATH_R" when both apply (the sweep is the stronger statement,
    and it is what keeps an unanswered flashing line); "" = not active."""
    ps = set(paths or ())
    if "B" in ps and ps & {"A", "R"}:
        return "BOTH"
    if "A" in ps:
        return "PATH_A"
    if "R" in ps:
        return "PATH_R"
    return "PATH_B" if "B" in ps else ""


def transition_trigger(geom, confirmed_selection, edge_id) -> str:
    """"PATH_A" | "PATH_B" | "PATH_R" | "BOTH" | "" — which path put this transition in scope. UI-facing."""
    return trigger_token(transition_paths(geom, confirmed_selection).get(str(edge_id), ()))


# ---------------------------------------------------------------------------
# 2. The band (§3)
# ---------------------------------------------------------------------------
def _rise_above_edge(geom, transition, face_id: str) -> float:
    """How far (ft) the facet's highest point rises above the shared edge's HIGHEST point. The edge's
    max z, not path[0]: a sloped shared edge must not be able to skew the comparison."""
    edge_z = max(float(geom.points[pid][2]) for pid in geom.lines[transition.edge_id].path)
    face = geom.faces[face_id]
    return max(float(geom.points[pid][2]) for lid in face.line_ids for pid in geom.lines[lid].path) - edge_z


def upper_face_id(geom, transition) -> str:
    """The UPPER facet of a transition, resolved for the PAIR (Joseph 2026-10-25): the facet that rises
    FURTHER above the shared edge. No tolerance — a tolerance is a guess, and 1/12 over a long run
    genuinely rises. Structurally incapable of both-UPPER or both-LOWER.

    If NEITHER facet rises above the edge it is a ridge, not a pitch transition; if both rise exactly
    equally there is no upper slope to name. Picking one would be inventing an answer, so it RAISES.
    (Unreachable on every fixture: the detector's same-fall condition excludes all 53 such candidate
    edges across Yager, Devore, Pershing, N St James and Killarney — verified in v91.)"""
    ra = _rise_above_edge(geom, transition, transition.face_a_id)
    rb = _rise_above_edge(geom, transition, transition.face_b_id)
    if ra <= 0.0 and rb <= 0.0:
        raise ValueError(f"transition {transition.edge_id}: neither facet rises above the shared edge "
                         f"(a ridge, not a pitch transition) — refusing to pick an upper slope")
    if ra == rb:
        raise ValueError(f"transition {transition.edge_id}: both facets rise equally above the edge — "
                         f"no upper slope to name")
    return str(transition.face_a_id if ra > rb else transition.face_b_id)


def transition_band_for_face(geom, transition, face_id: str,
                             shake_measurements: Optional[Mapping[str, object]] = None) -> Mapping[str, object]:
    """The tear-off band this transition carves on ONE of its two facets, in that facet's frame.

    Which facet is the UPPER slope is read from 3-D ELEVATION, never assumed — and since v91 it is
    resolved for the PAIR, not per facet (upper_face_id below): of the two facets sharing the edge, the
    one whose highest point rises FURTHER above the edge is UPPER and the other is LOWER. The v90 per-facet
    test ("rises above edge path[0] by >1e-6") marked BOTH Killarney L24/L34 facets UPPER — the 1/12 flat
    side's 'rise' was a corner 0.05 in high, or the sloped edge's own far endpoint — and its UPPER band
    then pointed off the facet and carved 0.0 SF, so the lower slope's tear-off silently vanished.

    (A tempting shortcut — "the edge sits at the facet's min-y, so the facet is above it" — is WRONG
    here and was caught in testing: these facets are not rectangles. On Yager's L33, facet V is
    stepped, so the shared edge lies partway up V's frame with most of V's vertices BELOW it, yet V
    genuinely rises above the edge (to z=0.00 vs the edge's z=-1.625) and IS the upper slope.
    Elevation is the only honest test.)

    The band is then aimed INTO the facet from the edge: up-slope (+y) three courses (to the top of
    the 3rd course, three_course_extent_ft) on the upper facet,
    down-slope (-y) one course on the lower one. It is clipped to the facet by affected_area, so a
    short upper slope simply yields a shorter band rather than spilling off the roof.
    """
    frame = geom.face_frame(face_id)
    line = geom.lines[transition.edge_id]
    a = frame(geom.points[line.path[0]])
    b = frame(geom.points[line.path[-1]])

    edge_y = (float(a[1]) + float(b[1])) / 2.0
    x_lo, x_hi = sorted((float(a[0]), float(b[0])))

    if face_id not in (transition.face_a_id, transition.face_b_id):
        raise ValueError(f"{face_id} is not a facet of transition {transition.edge_id}")
    is_upper = str(face_id) == upper_face_id(geom, transition)

    prof = resolve_shake_measurements(shake_measurements)
    course_ft = float(prof["exposure_in"]) / 12.0

    if is_upper:
        # UPPER slope — to the TOP of the 3rd course, measured UP-slope from the edge (v90; was 36 in).
        band = {"x0": x_lo, "x1": x_hi, "y0": edge_y, "y1": edge_y + three_course_extent_ft(shake_measurements), "side": UPPER}
    else:
        # LOWER slope — ONE course measured DOWN-slope from the edge (course-lap requirement).
        band = {"x0": x_lo, "x1": x_hi, "y0": edge_y - LOWER_BAND_COURSES * course_ft,
                "y1": edge_y, "side": LOWER}
    band["edge_id"] = transition.edge_id
    band["face_id"] = face_id
    band["edge_total_LF"] = float(transition.edge_total_LF)
    band["course_ft"] = course_ft
    return band


def transition_bands_by_face(geom, confirmed_selection,
                             shake_measurements: Optional[Mapping[str, object]] = None) -> dict:
    """{face_id: [band, ...]} for every facet touched by an ACTIVE transition — by EITHER path.

    Build 2b: Path A carves the band too, and this is required, not cosmetic. On Yager's L33 the
    valley repair sweeps facet V 100% but facet P 0%: the LOWER slope is never opened. Without the
    carve the tool would bill transition flashing that cannot physically be installed — the tie-in
    runs three courses above the edge and the 6 in metal laps over the lower courses, and you
    cannot do either through shakes that are still nailed down. Standard union rules apply, so the
    band adds ~0 SF on V (already swept) and real area on P.

    v91 MEMBRANE: when the user recorded metal == MEMBRANE, the membrane is the existing flashing and
    stays in place, so the MEMBRANE (LOWER) side is not disturbed and gets NO band. The steep (UPPER)
    side is still opened — three courses lifted to tuck the membrane under — so its band is unchanged.
    Every other answer, and an unanswered transition, carves both bands exactly as in v90.

    v92 REPLACED FACET (Joseph 2026-10-26, approved): a band on a FULLY REPLACED facet lies inside a facet
    already 100% scoped, so it contributes nothing — the rule v72 enforced in module2_assembly only. The
    diagram reads these same bands and drew that band as EXTRA area (v91: Path B on L79 with F16 replaced,
    scope 3431 / 1921.0 vs diagram 3643 / 2024.0); Path R made it reachable on every replacement. The rule
    now lives HERE, the one band authority both readers use, so they cannot disagree. The untouched
    neighbouring slope still carves its band ("the band still carves the untouched slope", 2026-10-25)."""
    bands: dict = {}
    metal = transition_metal_facts(confirmed_selection)
    replaced = replaced_face_ids(confirmed_selection)
    for transition in active_transitions(geom, confirmed_selection):
        membrane = metal.get(str(transition.edge_id)) == METAL_MEMBRANE
        for face_id in (transition.face_a_id, transition.face_b_id):
            if str(face_id) in replaced:
                continue                                    # unioned into the full replacement
            band = transition_band_for_face(geom, transition, face_id, shake_measurements)
            if membrane and band["side"] == LOWER:
                continue                                    # the membrane side is not disturbed
            bands.setdefault(face_id, []).append(band)
    return bands


def engine_bands(bands: Sequence[Mapping[str, object]]) -> List[Mapping[str, float]]:
    """Strip to the four numbers geometry_core.affected_area consumes."""
    return [{"x0": float(b["x0"]), "x1": float(b["x1"]), "y0": float(b["y0"]), "y1": float(b["y1"])}
            for b in (bands or [])]
