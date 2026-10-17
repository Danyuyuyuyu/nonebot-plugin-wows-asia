"""SQLite persistence for bindings, tracked accounts, per-ship snapshots and derived battle records."""
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

from .stats import STAT_FIELDS, Stat

_COLS = ", ".join(STAT_FIELDS)
_Q = ", ".join("?" * len(STAT_FIELDS))

_STATDEF = ", ".join(f"{c} INTEGER NOT NULL DEFAULT 0" for c in STAT_FIELDS)
# Columns added after the first release: (table, column, definition). Applied with ALTER TABLE on old databases.
_LATER = [("battle_record", "solo", "INTEGER"), ("battle_record", "div2", "INTEGER"), ("battle_record", "div3", "INTEGER"),
          ("battle_record", "full", "INTEGER NOT NULL DEFAULT 0"), ("battle_record", "best", "INTEGER NOT NULL DEFAULT 0"),
          ("battle_record", "end_battles", "INTEGER"),
          ("ship_state", "full", "INTEGER NOT NULL DEFAULT 0"), ("ship_state", "best_damage", "INTEGER"),
          ("ship_state", "best_frags", "INTEGER"), ("ship_state", "best_xp", "INTEGER")]
BEST_DAMAGE, BEST_FRAGS, BEST_XP = 1, 2, 4

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS binding (user_key TEXT PRIMARY KEY, account_id INTEGER NOT NULL,
    nickname TEXT NOT NULL, bound_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS tracked (account_id INTEGER PRIMARY KEY, nickname TEXT NOT NULL,
    baseline_at INTEGER, last_battle_time INTEGER NOT NULL DEFAULT 0, last_polled_at INTEGER NOT NULL DEFAULT 0,
    last_requested_at INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS ship_state (account_id INTEGER NOT NULL, ship_id INTEGER NOT NULL, mode TEXT NOT NULL,
    {_STATDEF}, PRIMARY KEY (account_id, ship_id, mode));
CREATE TABLE IF NOT EXISTS battle_record (id INTEGER PRIMARY KEY AUTOINCREMENT, account_id INTEGER NOT NULL,
    captured_at INTEGER NOT NULL, prev_at INTEGER NOT NULL, ship_id INTEGER NOT NULL, mode TEXT NOT NULL,
    {_STATDEF}, career_avg_damage REAL);
CREATE INDEX IF NOT EXISTS idx_record_account_time ON battle_record (account_id, captured_at);
"""


@dataclass
class Tracked:
    account_id: int
    nickname: str
    baseline_at: int | None
    last_battle_time: int
    last_polled_at: int
    last_requested_at: int


@dataclass
class Record:
    account_id: int
    captured_at: int
    prev_at: int
    ship_id: int
    mode: str
    stat: Stat
    career_avg_damage: float | None
    division: tuple[int, int, int] | None = None  # random only: (solo, div2, div3) battles; None = unknown
    full: bool = True  # detail fields (scouting, potential...) valid; False for pre-0.2.7 snapshots
    best: int = 0  # BEST_* bitmask: this window raised the ship's personal best
    end_battles: int | None = None  # ship's cumulative battle count after this window (dedupe key)


class Storage:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)
            later = [(t, c, "INTEGER NOT NULL DEFAULT 0") for t in ("ship_state", "battle_record") for c in STAT_FIELDS]
            for table, col, definition in later + _LATER:  # upgrade databases from older versions in place
                cols = {row[1] for row in self._db.execute(f"PRAGMA table_info({table})")}
                if col not in cols:
                    self._db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")
            # one record per battle window: a window ending at the same cumulative count can never be stored twice
            # (rows from before 0.2.8 have NULL here, which UNIQUE allows any number of times)
            self._db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_record_window "
                             "ON battle_record (account_id, ship_id, mode, end_battles)")
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _all(self, sql: str, args=()):
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    def _run(self, sql: str, args=()):
        with self._lock:
            self._db.execute(sql, args)
            self._db.commit()

    # ---- bindings ----
    def bind(self, user_key: str, account_id: int, nickname: str, now: int) -> None:
        self._run("INSERT INTO binding VALUES (?,?,?,?) ON CONFLICT(user_key) DO UPDATE SET "
                  "account_id=excluded.account_id, nickname=excluded.nickname, bound_at=excluded.bound_at",
                  (user_key, account_id, nickname, now))

    def unbind(self, user_key: str) -> bool:
        with self._lock:
            cur = self._db.execute("DELETE FROM binding WHERE user_key=?", (user_key,))
            self._db.commit()
            return cur.rowcount > 0

    def binding(self, user_key: str) -> tuple[int, str] | None:
        rows = self._all("SELECT account_id, nickname FROM binding WHERE user_key=?", (user_key,))
        return (rows[0][0], rows[0][1]) if rows else None

    def bound_ids(self) -> set[int]:
        return {r[0] for r in self._all("SELECT DISTINCT account_id FROM binding")}

    # ---- tracked accounts ----
    def tracked(self, account_id: int) -> Tracked | None:
        rows = self._all("SELECT * FROM tracked WHERE account_id=?", (account_id,))
        return Tracked(*rows[0]) if rows else None

    def all_tracked(self) -> list[Tracked]:
        return [Tracked(*r) for r in self._all("SELECT * FROM tracked")]

    def count_tracked(self) -> int:
        return self._all("SELECT COUNT(*) FROM tracked")[0][0]

    def ensure_tracked(self, account_id: int, nickname: str, now: int) -> None:
        self._run("INSERT INTO tracked (account_id, nickname, last_requested_at) VALUES (?,?,?) "
                  "ON CONFLICT(account_id) DO UPDATE SET nickname=excluded.nickname, "
                  "last_requested_at=excluded.last_requested_at", (account_id, nickname, now))

    def mark_polled(self, account_id: int, now: int, last_battle_time: int | None, baseline: bool) -> None:
        with self._lock:
            if last_battle_time is not None:
                self._db.execute("UPDATE tracked SET last_battle_time=? WHERE account_id=?",
                                 (last_battle_time, account_id))
            self._db.execute("UPDATE tracked SET last_polled_at=? WHERE account_id=?", (now, account_id))
            if baseline:
                self._db.execute("UPDATE tracked SET baseline_at=? WHERE account_id=?", (now, account_id))
            self._db.commit()

    def untrack(self, account_id: int) -> None:
        with self._lock:
            for table in ("tracked", "ship_state", "battle_record"):
                self._db.execute(f"DELETE FROM {table} WHERE account_id=?", (account_id,))
            self._db.commit()

    # ---- snapshots ----
    def ship_states(self, account_id: int) -> dict[tuple[int, str], Stat]:
        rows = self._all(f"SELECT ship_id, mode, {_COLS} FROM ship_state WHERE account_id=?", (account_id,))
        return {(r[0], r[1]): Stat(*r[2:]) for r in rows}

    def ship_meta(self, account_id: int) -> dict[tuple[int, str], tuple[bool, tuple[int, int, int] | None]]:
        """(detail fields valid, stored personal bests) per ship/mode."""
        rows = self._all("SELECT ship_id, mode, full, best_damage, best_frags, best_xp FROM ship_state "
                         "WHERE account_id=?", (account_id,))
        return {(r[0], r[1]): (bool(r[2]), None if r[3] is None else (r[3], r[4], r[5])) for r in rows}

    def stale_accounts(self) -> set[int]:
        """Accounts whose snapshot predates the detail fields: re-snapshot once without waiting for a battle."""
        return {r[0] for r in self._all("SELECT DISTINCT account_id FROM ship_state WHERE full=0")}

    def mark_full(self, account_id: int) -> None:
        self._run("UPDATE ship_state SET full=1 WHERE account_id=? AND full=0", (account_id,))

    def save_snapshot(self, account_id: int, states: dict[tuple[int, str], Stat], records: list[Record],
                      bests: dict[tuple[int, str], tuple[int, int, int]] | None = None) -> int:
        """Store snapshots and records in one transaction. Returns how many records were new
        (a window already stored - same ship, mode and end_battles - is ignored)."""
        bests = bests or {}
        inserted = 0
        with self._lock:
            for (ship_id, mode), stat in states.items():
                best = bests.get((ship_id, mode)) or (None, None, None)
                self._db.execute(f"INSERT OR REPLACE INTO ship_state (account_id, ship_id, mode, {_COLS}, full, "
                                 f"best_damage, best_frags, best_xp) VALUES (?,?,?,{_Q},1,?,?,?)",
                                 (account_id, ship_id, mode, *stat.as_tuple(), *best))
            for rec in records:
                cur = self._db.execute(f"INSERT OR IGNORE INTO battle_record (account_id, captured_at, prev_at, "
                                       f"ship_id, mode, {_COLS}, career_avg_damage, solo, div2, div3, full, best, "
                                       f"end_battles) VALUES (?,?,?,?,?,{_Q},?,?,?,?,?,?,?)",
                                       (rec.account_id, rec.captured_at, rec.prev_at, rec.ship_id, rec.mode,
                                        *rec.stat.as_tuple(), rec.career_avg_damage,
                                        *(rec.division or (None,) * 3), int(rec.full), rec.best, rec.end_battles))
                inserted += cur.rowcount
            self._db.commit()
        return inserted

    def records(self, account_id: int, since: int) -> list[Record]:
        rows = self._all(f"SELECT account_id, captured_at, prev_at, ship_id, mode, {_COLS}, career_avg_damage, "
                         "solo, div2, div3, full, best, end_battles FROM battle_record WHERE account_id=? AND captured_at>=? "
                         "ORDER BY captured_at DESC, id DESC", (account_id, since))
        n = len(STAT_FIELDS)
        return [Record(r[0], r[1], r[2], r[3], r[4], Stat(*r[5:5 + n]), r[5 + n],
                       None if r[6 + n] is None else tuple(r[6 + n:9 + n]), bool(r[9 + n]), r[10 + n] or 0, r[11 + n])
                for r in rows]

    def prune_records(self, before: int) -> None:
        self._run("DELETE FROM battle_record WHERE captured_at<?", (before,))
