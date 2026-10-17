"""Snapshot polling: per-ship totals are diffed between polls to recover individual battles."""
import time
from dataclasses import dataclass

from .api import WowsApi
from .commands import WowsError
from .stats import DIV_MODES, Stat, num, ship_bests, ship_states
from .storage import BEST_DAMAGE, BEST_FRAGS, BEST_XP, Record, Storage

RETRY_WINDOW = 3600  # keep re-checking an account for an hour if WG stats lag behind last_battle_time
MIN_REFRESH_GAP = 60
ACTIVE_WINDOW = 2 * 3600  # played within this window -> fast polling lane


@dataclass
class RefreshResult:
    hidden: bool = False
    baseline_created: bool = False
    new_records: int = 0
    skipped: bool = False


def diff_states(old: dict[tuple[int, str], Stat], new: dict[tuple[int, str], Stat],
                ) -> tuple[list[tuple[tuple[int, str], Stat, float | None]], dict[tuple[int, str], Stat]]:
    """Return (battle deltas, states to store). Inconsistent deltas re-baseline that ship silently."""
    deltas = []
    for key, now_stat in new.items():
        before = old.get(key, Stat())
        if now_stat.battles == before.battles:
            continue
        delta = now_stat - before
        if now_stat.battles < before.battles or not delta.valid_delta():
            continue  # data reset / anomaly: just store the new baseline
        career = before.damage / before.battles if before.battles else None
        deltas.append((key, delta, career))
    changed = {k: v for k, v in new.items() if old.get(k) != v}
    return deltas, changed


def split_divisions(deltas: list[tuple[tuple[int, str], Stat, float | None]],
                    ) -> list[tuple[tuple[int, str], Stat, float | None, tuple[int, int, int] | None]]:
    """Drop pvp_solo/div2/div3 deltas from the list and attach them to the matching random delta as
    (solo, div2, div3). Left unknown (None) unless the three add up exactly to the random delta, which
    also covers snapshots taken before division data was stored."""
    split: dict[int, list[int]] = {}
    out = []
    for (ship_id, mode), delta, career in deltas:
        if mode in DIV_MODES:
            split.setdefault(ship_id, [0, 0, 0])[DIV_MODES.index(mode)] = delta.battles
    for (ship_id, mode), delta, career in deltas:
        if mode in DIV_MODES:
            continue
        div = split.get(ship_id)
        ok = mode == "pvp" and div is not None and sum(div) == delta.battles
        out.append(((ship_id, mode), delta, career, tuple(div) if ok else None))
    return out


def best_flags(old: tuple[int, int, int] | None, new: tuple[int, int, int] | None) -> int:
    """Bitmask of personal bests raised between two snapshots (unknown old -> no flags)."""
    if old is None or new is None:
        return 0
    return sum(bit for bit, o, n in zip((BEST_DAMAGE, BEST_FRAGS, BEST_XP), old, new) if n > o)


class Tracker:
    def __init__(self, api: WowsApi, storage: Storage, *, track_days: int = 14, max_tracked: int = 200,
                 record_days: int = 30, poll_minutes: int = 10, fast_minutes: int = 0, clock=time.time):
        self.api = api
        self.storage = storage
        self.track_days = track_days
        self.max_tracked = max_tracked
        self.record_days = record_days
        self.poll_minutes = poll_minutes
        self.fast_minutes = fast_minutes if 0 < fast_minutes < poll_minutes else 0
        self.clock = clock
        self._last_full: int | None = None

    @property
    def tick_minutes(self) -> int:
        """Scheduler interval: the fast lane when enabled, otherwise the normal poll interval."""
        return self.fast_minutes or self.poll_minutes

    def interval_text(self) -> str:
        if self.fast_minutes:
            return f"已绑定或正在游戏的账号每约 {self.fast_minutes} 分钟检查一次，其余每约 {self.poll_minutes} 分钟"
        return f"每约 {self.poll_minutes} 分钟检查一次"

    def now(self) -> int:
        return int(self.clock())

    def touch(self, account_id: int, nickname: str) -> bool:
        """Start (or keep) tracking an account. False when the tracking quota is full."""
        if self.storage.tracked(account_id) is None and self.storage.count_tracked() >= self.max_tracked:
            if account_id not in self.storage.bound_ids():
                return False
        self.storage.ensure_tracked(account_id, nickname, self.now())
        return True

    async def refresh(self, account_id: int, *, last_battle_time: int | None = None,
                      force: bool = False) -> RefreshResult:
        tracked = self.storage.tracked(account_id)
        if tracked is None:
            return RefreshResult(skipped=True)
        now = self.now()
        has_baseline = tracked.baseline_at is not None
        if has_baseline and not force:
            if now - tracked.last_polled_at < MIN_REFRESH_GAP:
                return RefreshResult(skipped=True)
            if last_battle_time is not None and last_battle_time <= tracked.last_battle_time:
                return RefreshResult(skipped=True)
        ships = await self.api.ship_stats(account_id)
        if ships is None:
            self.storage.mark_polled(account_id, now, None, False)
            return RefreshResult(hidden=True)
        new, bests = ship_states(ships), ship_bests(ships)
        if not has_baseline:
            self.storage.save_snapshot(account_id, new, [], bests)
            self.storage.mark_polled(account_id, now, last_battle_time or 0, True)
            return RefreshResult(baseline_created=True)
        old, meta = self.storage.ship_states(account_id), self.storage.ship_meta(account_id)
        deltas, changed = diff_states(old, new)
        # rows saved before 0.2.7 have no detail fields: rewrite them now so the next battle is complete
        changed.update({k: v for k, v in new.items() if k in meta and not meta[k][0]})
        prev_at = tracked.last_polled_at or tracked.baseline_at or now
        records = []
        for (ship_id, mode), delta, career, div in split_divisions(deltas):
            full, old_best = meta.get((ship_id, mode), (True, None))
            records.append(Record(account_id, now, prev_at, ship_id, mode, delta, career, div,
                                  full=full, best=best_flags(old_best, bests.get((ship_id, mode)))))
        self.storage.save_snapshot(account_id, changed, records, bests)
        self.storage.mark_full(account_id)
        marker = last_battle_time
        if marker is not None and not records and now - marker < RETRY_WINDOW:
            marker = None  # WG may not have published ship stats yet: retry next poll
        self.storage.mark_polled(account_id, now, marker, False)
        return RefreshResult(new_records=len(records))

    def prune(self) -> list[int]:
        now = self.now()
        bound = self.storage.bound_ids()
        removed = []
        for t in self.storage.all_tracked():
            if t.account_id not in bound and now - t.last_requested_at > self.track_days * 86400:
                self.storage.untrack(t.account_id)
                removed.append(t.account_id)
        self.storage.prune_records(now - self.record_days * 86400)
        return removed

    async def poll_all(self) -> int:
        """One scheduler tick. Returns the number of new battle records."""
        if not self.api.configured:
            return 0
        self.prune()
        tracked = self.storage.all_tracked()
        now = self.now()
        tick = self.tick_minutes * 60
        if self._last_full is None or now - self._last_full + tick / 2 >= self.poll_minutes * 60:
            self._last_full = now  # full tick: every tracked account
        else:  # fast tick: bound accounts, accounts without a baseline yet, and accounts that played recently
            bound = self.storage.bound_ids()
            tracked = [t for t in tracked if t.account_id in bound or t.baseline_at is None
                       or now - t.last_battle_time < ACTIVE_WINDOW]
        if not tracked:
            return 0
        infos = await self.api.account_info([t.account_id for t in tracked], full=False)
        stale = self.storage.stale_accounts()
        total = 0
        for t in tracked:
            info = infos.get(t.account_id)
            if not info or info.get("hidden_profile") is True:
                continue
            lbt = num(info.get("last_battle_time"))
            if t.baseline_at is not None and (lbt is None or lbt <= t.last_battle_time) and t.account_id not in stale:
                continue
            try:
                total += (await self.refresh(t.account_id, last_battle_time=lbt, force=True)).new_records
            except WowsError:
                continue  # transient API trouble: try again next tick
        return total
