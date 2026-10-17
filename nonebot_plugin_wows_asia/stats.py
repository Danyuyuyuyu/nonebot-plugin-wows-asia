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
    mb = block.get("main_battery") if isinstance(block.get("main_battery"), dict) else {}
    g = lambda d, k: num(d.get(k)) or 0  # noqa: E731
    return Stat(battles, g(block, "wins"), g(block, "losses"), g(block, "damage_dealt"), g(block, "frags"),
                g(block, "xp"), g(block, "survived_battles"), g(mb, "hits"), g(mb, "shots"))


MODES = ("pvp", "rank_solo")
# Random-battle split by team size; stored as extra ship_state modes (battles only), never as records.
DIV_MODES = ("pvp_solo", "pvp_div2", "pvp_div3")


def ship_states(ships: list[dict]) -> dict[tuple[int, str], Stat]:
    out = {}
    for ship in ships:
        for mode in MODES + DIV_MODES:
            stat = parse_stat(ship.get(mode))
            if stat is not None and stat.battles > 0:
                out[(ship["ship_id"], mode)] = stat
    return out
