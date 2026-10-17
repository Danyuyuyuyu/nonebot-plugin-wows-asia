import math
from dataclasses import dataclass, fields
from typing import Any


def num(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return int(value)


@dataclass
class Stat:
    battles: int = 0
    wins: int = 0
    losses: int = 0
    damage: int = 0
    frags: int = 0
    xp: int = 0
    survived: int = 0
    hits: int = 0
    shots: int = 0
    # detail fields (0.2.7+): only meaningful on records/states with full=True
    scouting: int = 0  # damage_scouting
    potential: int = 0  # art_agro + torpedo_agro
    spotted: int = 0
    planes: int = 0
    torp_hits: int = 0
    torp_shots: int = 0
    sec_hits: int = 0
    sec_shots: int = 0
    mb_frags: int = 0
    torp_frags: int = 0
    sec_frags: int = 0
    cap: int = 0  # capture_points
    defend: int = 0  # dropped_capture_points

    @property
    def draws(self) -> int:
        return max(self.battles - self.wins - self.losses, 0)

    def __add__(self, other: "Stat") -> "Stat":
        return Stat(*(getattr(self, f.name) + getattr(other, f.name) for f in fields(Stat)))

    def __sub__(self, other: "Stat") -> "Stat":
        return Stat(*(getattr(self, f.name) - getattr(other, f.name) for f in fields(Stat)))

    def valid_delta(self) -> bool:
        return all(getattr(self, f.name) >= 0 for f in fields(Stat)) and self.wins + self.losses <= self.battles \
            and self.survived <= self.battles

    def as_tuple(self) -> tuple[int, ...]:
        return tuple(getattr(self, f.name) for f in fields(Stat))

    # ratios: None when undefined
    def per(self, attr: str) -> float | None:
        return getattr(self, attr) / self.battles if self.battles else None

    @property
    def win_rate(self) -> float | None:
        return self.wins / self.battles * 100 if self.battles else None

    @property
    def survival(self) -> float | None:
        return self.survived / self.battles * 100 if self.battles else None

    @property
    def hit_rate(self) -> float | None:
        return self.hits / self.shots * 100 if self.shots else None


STAT_FIELDS = [f.name for f in fields(Stat)]


def parse_stat(block: Any) -> Stat | None:
    """WG statistics block -> Stat. None when battles is missing/invalid."""
    if not isinstance(block, dict):
        return None
    battles = num(block.get("battles"))
    if battles is None:
        return None
    sub = lambda k: block.get(k) if isinstance(block.get(k), dict) else {}  # noqa: E731
    mb, tp, sb = sub("main_battery"), sub("torpedoes"), sub("second_battery")
    g = lambda d, k: num(d.get(k)) or 0  # noqa: E731
    return Stat(battles, g(block, "wins"), g(block, "losses"), g(block, "damage_dealt"), g(block, "frags"),
                g(block, "xp"), g(block, "survived_battles"), g(mb, "hits"), g(mb, "shots"),
                g(block, "damage_scouting"), g(block, "art_agro") + g(block, "torpedo_agro"),
                g(block, "ships_spotted"), g(block, "planes_killed"), g(tp, "hits"), g(tp, "shots"),
                g(sb, "hits"), g(sb, "shots"), g(mb, "frags"), g(tp, "frags"), g(sb, "frags"),
                g(block, "capture_points"), g(block, "dropped_capture_points"))


BEST_KEYS = ("max_damage_dealt", "max_frags_battle", "max_xp")  # per-ship personal bests -> "新纪录" flags


def parse_best(block: Any) -> tuple[int, int, int] | None:
    if not isinstance(block, dict):
        return None
    vals = [num(block.get(k)) for k in BEST_KEYS]
    return None if any(v is None for v in vals) else tuple(vals)


MODES = ("pvp", "rank_solo")
# Random-battle split by team size; stored as extra ship_state modes (battles only), never as records.
DIV_MODES = ("pvp_solo", "pvp_div2", "pvp_div3")


def ship_bests(ships: list[dict]) -> dict[tuple[int, str], tuple[int, int, int]]:
    out = {}
    for ship in ships:
        for mode in MODES:
            best = parse_best(ship.get(mode))
            if best is not None:
                out[(ship["ship_id"], mode)] = best
    return out


def ship_states(ships: list[dict]) -> dict[tuple[int, str], Stat]:
    out = {}
    for ship in ships:
        for mode in MODES + DIV_MODES:
            stat = parse_stat(ship.get(mode))
            if stat is not None and stat.battles > 0:
                # team-size modes keep battle counts only, so stored snapshots stay comparable across versions
                out[(ship["ship_id"], mode)] = Stat(stat.battles) if mode in DIV_MODES else stat
    return out
