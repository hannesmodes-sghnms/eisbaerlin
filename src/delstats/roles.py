from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Any, Iterable, Mapping

# EBB-specific role overrides. The DEL roster lists Eric Mik as a defenseman,
# but he is also deployed as a forward. Keep roster position and on-ice role
# separate so a 3F/2D unit is not misclassified as 2F/3D solely because of the
# static roster entry.
DEFAULT_FLEXIBLE_ROLES: dict[int, tuple[str, ...]] = {
    1425: ("FO", "DE"),  # Eric Mik
}


@dataclass(frozen=True)
class RoleResolution:
    forwards: tuple[int, ...]
    defense: tuple[int, ...]
    assignments: dict[int, str]
    standard: bool
    shape: str
    inferred_player_ids: tuple[int, ...]


def _player_position(player: Mapping[str, Any] | None) -> str:
    return str((player or {}).get("position") or "").upper()


def resolve_skater_roles(
    player_ids: Iterable[int],
    players: Mapping[int, Mapping[str, Any]],
    *,
    flexible_roles: Mapping[int, Iterable[str]] | None = None,
) -> RoleResolution:
    """Resolve on-ice forward/defense roles for one five-skater unit.

    Roster position remains the default. Players in ``flexible_roles`` may be
    assigned to another allowed role when that produces a normal 3F/2D unit.
    This is intentionally deterministic and conservative: a role change only
    beats the roster assignment when it improves the five-skater shape.
    """

    ids = tuple(sorted({int(pid) for pid in player_ids}))
    flex = {int(pid): tuple(str(role).upper() for role in roles) for pid, roles in (flexible_roles or DEFAULT_FLEXIBLE_ROLES).items()}

    allowed: list[tuple[str, ...]] = []
    roster_positions: list[str] = []
    inferred_candidates: set[int] = set()
    for pid in ids:
        roster = _player_position(players.get(pid))
        roster_positions.append(roster)
        if pid in flex:
            roles = tuple(role for role in flex[pid] if role in {"FO", "DE"})
            if roles:
                allowed.append(roles)
                if len(set(roles)) > 1:
                    inferred_candidates.add(pid)
                continue
        if roster in {"FO", "DE"}:
            allowed.append((roster,))
        else:
            # Unknown skater positions are rare. Allow either role but penalize
            # the inference so known roster positions always win when possible.
            allowed.append(("FO", "DE"))
            inferred_candidates.add(pid)

    if not ids:
        return RoleResolution((), (), {}, False, "0F/0D", ())

    best: tuple[tuple[int, int, int, tuple[str, ...]], tuple[str, ...]] | None = None
    for assignment in product(*allowed):
        f_count = sum(role == "FO" for role in assignment)
        d_count = sum(role == "DE" for role in assignment)
        standard_penalty = 0 if len(ids) == 5 and f_count == 3 and d_count == 2 else 100 + abs(f_count - 3) * 10 + abs(d_count - 2) * 10
        roster_changes = sum(
            1
            for role, roster in zip(assignment, roster_positions)
            if roster in {"FO", "DE"} and role != roster
        )
        unknown_inferences = sum(1 for roster in roster_positions if roster not in {"FO", "DE"})
        # Final tuple makes selection deterministic if multiple assignments tie.
        score = (standard_penalty, roster_changes, unknown_inferences, assignment)
        if best is None or score < best[0]:
            best = (score, assignment)

    assert best is not None
    assignment = best[1]
    assignments = {pid: role for pid, role in zip(ids, assignment)}
    forwards = tuple(pid for pid in ids if assignments[pid] == "FO")
    defense = tuple(pid for pid in ids if assignments[pid] == "DE")
    standard = len(ids) == 5 and len(forwards) == 3 and len(defense) == 2
    inferred = tuple(
        pid
        for pid, role, roster in zip(ids, assignment, roster_positions)
        if pid in inferred_candidates and role != roster
    )
    return RoleResolution(
        forwards=forwards,
        defense=defense,
        assignments=assignments,
        standard=standard,
        shape=f"{len(forwards)}F/{len(defense)}D",
        inferred_player_ids=inferred,
    )
