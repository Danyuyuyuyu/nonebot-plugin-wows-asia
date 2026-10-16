"""Snapshot polling: per-ship totals are diffed between polls to recover individual battles."""
import time
from dataclasses import dataclass

from .api import WowsApi
from .commands import WowsError
from .stats import Stat, num, ship_states
from .storage import Record, Storage

RETRY_WINDOW = 3600  # keep re-checking an account for an hour if WG stats lag behind last_battle_time
MIN_REFRESH_GAP = 60


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


class Tracker:
    def __init__(self, api: WowsApi, storage: Storage, *, track_days: int = 14, max_tracked: int = 200,
                 record_days: int = 30, clock=time.time):
        self.api = api
        self.storage = storage
        self.track_days = track_days
        self.max_tracked = max_tracked
        self.record_days = record_days
        self.clock = clock

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
        new = ship_states(ships)
        if not has_baseline:
            self.storage.save_snapshot(account_id, new, [])
            self.storage.mark_polled(account_id, now, last_battle_time or 0, True)
            return RefreshResult(baseline_created=True)
        deltas, changed = diff_states(self.storage.ship_states(account_id), new)
        prev_at = tracked.last_polled_at or tracked.baseline_at or now
        records = [Record(account_id, now, prev_at, ship_id, mode, delta, career)
                   for (ship_id, mode), delta, career in deltas]
        self.storage.save_snapshot(account_id, changed, records)
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
        if not tracked:
            return 0
        infos = await self.api.account_info([t.account_id for t in tracked], full=False)
        total = 0
        for t in tracked:
            info = infos.get(t.account_id)
            if not info or info.get("hidden_profile") is True:
                continue
            lbt = num(info.get("last_battle_time"))
            if t.baseline_at is not None and (lbt is None or lbt <= t.last_battle_time):
                continue
            try:
                total += (await self.refresh(t.account_id, last_battle_time=lbt, force=True)).new_records
            except WowsError:
                continue  # transient API trouble: try again next tick
        return total
