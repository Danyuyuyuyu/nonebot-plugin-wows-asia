"""Turn raw WG data + local records into display-ready view models (no HTML here)."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from .api import ShipInfo
from .stats import Stat, num, parse_stat
from .storage import Record
from .ship_names import SHIP_NAMES

CST = timezone(timedelta(hours=8))
TYPE_CN = {"Battleship": "战列舰", "Cruiser": "巡洋舰", "Destroyer": "驱逐舰", "AirCarrier": "航母",
           "Submarine": "潜艇"}
TYPE_ORDER = ["战列舰", "巡洋舰", "驱逐舰", "航母", "潜艇", "其他"]
ROMAN = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI"]
MODE_CN = {"pvp": "随机", "rank_solo": "排位"}


def clean(value: Any, limit: int = 40) -> str:
    return "".join(c for c in str(value) if c.isprintable())[:limit]


def day_of(ts: int):
    return datetime.fromtimestamp(ts, CST).date()


def fmt_time(ts: int, pattern: str = "%H:%M") -> str:
    return datetime.fromtimestamp(ts, CST).strftime(pattern)


def roman(tier: int) -> str:
    return ROMAN[tier] if 0 < tier < len(ROMAN) else "?"


@dataclass
class Identity:
    account_id: int
    nickname: str
    clan: str = ""
    clan_name: str = ""
    clan_color: str = ""
    clan_league: str = ""


@dataclass
class StateView:
    kind: str  # hidden | tracking | idle | newbie | quota
    card_title: str
    who: Identity
    sub: str
    heading: str
    text: str
    tip: str


@dataclass
class TypeRow:
    name: str
    battles: int
    wins: int
    damage: int


@dataclass
class TierRow:
    tier: int
    battles: int
    wins: int
    damage: int


@dataclass
class TotalView:
    who: Identity
    created_at: int | None
    random: Stat
    ranked: Stat | None
    types: list[TypeRow]
    divisions: list[tuple[str, int, int]]
    records: list[tuple[str, int, str]]
    generated_at: int
    tiers: list[TierRow] = field(default_factory=list)


@dataclass
class BattleRow:
    time: str
    time_end: str
    mode: str
    ship: str
    ship_type: str
    tier: str
    stat: Stat
    career_avg_damage: float | None
    team: str = ""  # 单野 / 双排 / 三排, or "单野2 双排1" for merged rows; "" = unknown or ranked
    date: str = ""  # MM-DD, shown in flat (sorted) lists


@dataclass
class DayGroup:
    label: str
    stat: Stat
    rows: list[BattleRow]


@dataclass
class RecentView:
    who: Identity
    start: str
    end: str
    summary: Stat
    prev_battles: int | None
    tracking_since: str
    career: Stat
    days: list[tuple[str, Stat | None]]  # None = not tracked yet that day
    groups: list[DayGroup]
    hidden_rows: int
    generated_at: int
    notes: list[str] = field(default_factory=list)
    teams: tuple[int, int, int] | None = None  # random battles in 7 days by team size (known rows only)


TEAM_CN = ("单野", "双排", "三排")


def team_label(division: tuple[int, int, int] | None) -> str:
    parts = [(name, n) for name, n in zip(TEAM_CN, division or ()) if n]
    if sum(n for _, n in parts) == 1:
        return parts[0][0]  # a single battle: just "单野" / "双排" / "三排"
    return " ".join(f"{name}{n}" for name, n in parts)


def ship_label(info: ShipInfo | None, ship_id: int) -> tuple[str, str, str]:
    fallback = f"未知战舰 {ship_id}" if info is None else info.name
    name = SHIP_NAMES.name_for(ship_id, fallback)
    if info is None:
        return clean(name, 24), "其他", "?"
    return clean(name, 24), TYPE_CN.get(info.type, "其他"), roman(info.tier)


def career_random(account: dict) -> Stat:
    stats = account.get("statistics") if isinstance(account.get("statistics"), dict) else {}
    return parse_stat(stats.get("pvp")) or Stat()


def build_total(who: Identity, account: dict, ships: list[dict] | None, infos: dict[int, ShipInfo],
                now: int) -> TotalView:
    stats = account.get("statistics") if isinstance(account.get("statistics"), dict) else {}
    pvp_raw = stats.get("pvp") if isinstance(stats.get("pvp"), dict) else {}
    random = parse_stat(pvp_raw) or Stat()
    ranked = parse_stat(stats.get("rank_solo"))
    by_type: dict[str, TypeRow] = {}
    by_tier = {t: TierRow(t, 0, 0, 0) for t in range(1, 12)}
    for ship in ships or []:
        s = parse_stat(ship.get("pvp"))
        if not s or not s.battles:
            continue
        _, tname, _ = ship_label(infos.get(ship["ship_id"]), ship["ship_id"])
        if tname == "其他":
            continue  # removed/unlisted ships: not shown in type or tier breakdowns
        row = by_type.setdefault(tname, TypeRow(tname, 0, 0, 0))
        row.battles += s.battles
        row.wins += s.wins
        row.damage += s.damage
        info = infos.get(ship["ship_id"])
        if info and info.tier in by_tier:
            tr = by_tier[info.tier]
            tr.battles += s.battles
            tr.wins += s.wins
            tr.damage += s.damage
    types = sorted(by_type.values(), key=lambda r: (TYPE_ORDER.index(r.name), -r.battles))
    divisions = []
    for key, label in (("pvp_solo", "单野"), ("pvp_div2", "双排"), ("pvp_div3", "三排")):
        block = stats.get(key) if isinstance(stats.get(key), dict) else None
        b = num(block.get("battles")) if block else None
        if b:
            divisions.append((label, b, num(block.get("wins")) or 0))
    records = []
    for label, vkey, skey in (("单场最高伤害", "max_damage_dealt", "max_damage_dealt_ship_id"),
                              ("单场最高击沉", "max_frags_battle", "max_frags_ship_id"),
                              ("单场最高经验", "max_xp", "max_xp_ship_id"),
                              ("单场最高侦察", "max_damage_scouting", "max_scouting_damage_ship_id")):
        value = num(pvp_raw.get(vkey))
        if value is None:
            continue
        sid = num(pvp_raw.get(skey))
        name = ship_label(infos.get(sid), sid)[0] if sid and sid in infos else ""
        records.append((label, value, name))
    tiers = [by_tier[t] for t in range(1, 12)]
    if not any(t.battles for t in tiers):
        tiers = []
    elif not by_tier[11].battles:
        tiers = tiers[:10]  # only show XI when the player owns superships
    return TotalView(who, num(account.get("created_at")), random, ranked if ranked and ranked.battles else None,
                     types, divisions, records, now, tiers)


def total_ship_ids(account: dict, ships: list[dict] | None) -> list[int]:
    ids = [s["ship_id"] for s in ships or [] if isinstance(s.get("pvp"), dict) and num(s["pvp"].get("battles"))]
    stats = account.get("statistics") if isinstance(account.get("statistics"), dict) else {}
    pvp = stats.get("pvp") if isinstance(stats.get("pvp"), dict) else {}
    for key in ("max_damage_dealt_ship_id", "max_frags_ship_id", "max_xp_ship_id", "max_scouting_damage_ship_id"):
        sid = num(pvp.get(key))
        if sid:
            ids.append(sid)
    return list(dict.fromkeys(ids))


def build_recent(who: Identity, career: Stat, records: list[Record], infos: dict[int, ShipInfo],
                 baseline_at: int, now: int, max_rows: int = 12) -> RecentView:
    today = day_of(now)
    days7 = [today - timedelta(days=i) for i in range(6, -1, -1)]
    start7 = days7[0]
    base_day = day_of(baseline_at)
    in7 = [r for r in records if day_of(r.captured_at) >= start7]
    prev = [r for r in records if start7 - timedelta(days=7) <= day_of(r.captured_at) < start7]
    summary = sum((r.stat for r in in7), Stat())
    prev_battles = sum(r.stat.battles for r in prev) if base_day <= start7 - timedelta(days=7) else None
    per_day: dict = {}
    for r in in7:
        d = day_of(r.captured_at)
        per_day[d] = per_day.get(d, Stat()) + r.stat
    days = [(d.strftime("%m-%d"), per_day.get(d, Stat()) if d >= base_day else None) for d in days7]
    groups, shown = [], 0
    hidden = 0
    for d, label in ((today, f"今天 {today:%m-%d}"), (today - timedelta(days=1), f"昨天 {today - timedelta(days=1):%m-%d}")):
        recs = [r for r in in7 if day_of(r.captured_at) == d]
        if not recs:
            continue
        rows = []
        for r in recs:
            if shown >= max_rows:
                hidden += 1
                continue
            name, tname, tier = ship_label(infos.get(r.ship_id), r.ship_id)
            rows.append(BattleRow(fmt_time(r.captured_at), fmt_time(r.prev_at) if r.stat.battles > 1 and day_of(r.prev_at) == day_of(r.captured_at) else "",
                                  MODE_CN.get(r.mode, r.mode), name, tname, tier, r.stat, r.career_avg_damage,
                                  team_label(r.division)))
            shown += 1
        groups.append(DayGroup(label, sum((r.stat for r in recs), Stat()), rows))
    start = max(start7, base_day)
    known = [r.division for r in in7 if r.division]
    teams = tuple(sum(d[i] for d in known) for i in range(3)) if known else None
    return RecentView(who, start.strftime("%Y-%m-%d"), today.strftime("%m-%d"), summary, prev_battles,
                      fmt_time(baseline_at, "%m-%d %H:%M"), career, days, groups, hidden, now, teams=teams)


# ---- state cards ----
def state_hidden(who: Identity, title: str) -> StateView:
    return StateView("hidden", title, who, "战绩未公开", "该玩家隐藏了战绩",
                     "对方在游戏设置中关闭了公开战绩，WG 接口只返回昵称和账号 ID，无法读取任何统计数据。",
                     "如果是你自己的账号：在游戏设置中关闭“隐藏战绩”，稍后再查询即可。")


def state_tracking(who: Identity, baseline_at: int, interval: str) -> StateView:
    return StateView("tracking", "最近战绩", who, f"开始记录 · {fmt_time(baseline_at, '%Y-%m-%d %H:%M')}",
                     "还没有足够的近期数据",
                     f"已保存第一份战绩快照。之后{interval}，有新战斗就会记下每一场的数据。",
                     "现在可以先用 /wows 查看总战绩；打几场之后再查最近战绩就能看到场次明细。")


def state_idle(who: Identity, baseline_at: int) -> StateView:
    return StateView("idle", "最近战绩", who, f"记录中 · 自 {fmt_time(baseline_at, '%m-%d')} 起",
                     "近 7 天没有新战斗", "最近 7 天里没有记录到随机或排位战斗。",
                     "出海打几场之后再来查吧～ 总战绩可以用 /wows 查看。")


def state_quota(who: Identity) -> StateView:
    return StateView("quota", "最近战绩", who, "暂未记录", "追踪名额已满",
                     "机器人记录的玩家数量已到上限，暂时不能为这个账号开始记录。",
                     "绑定的账号不受名额限制：/wows 绑定 昵称；或请管理员调大 WOWS_MAX_TRACKED。")


def state_newbie(who: Identity, random: Stat, threshold: int) -> StateView:
    parts = []
    if random.win_rate is not None:
        parts.append(f"胜率 {random.win_rate:.1f}%")
    if random.battles:
        parts.append(f"场均伤害 {random.damage / random.battles:,.0f}")
        parts.append(f"场均击沉 {random.frags / random.battles:.2f}")
    tip = "基础数据：" + " · ".join(parts) + f" · 打满 {threshold} 场后显示完整卡片" if parts else \
        f"还没有随机战斗记录，打满 {threshold} 场后显示完整卡片。"
    return StateView("newbie", "总战绩", who, f"随机 {random.battles} 场", "场数还比较少",
                     f"随机战斗目前只有 {random.battles} 场，胜率和场均数据波动很大，暂不展示舰种和组队分析。", tip)


# ---- 场次 / 单场 ----
SORT_CN = {"damage": "伤害", "frags": "击沉", "xp": "经验", "scouting": "侦察伤害", "potential": "潜在伤害"}
SORT_ATTR = {"damage": "damage", "frags": "frags", "xp": "xp", "scouting": "scouting", "potential": "potential"}
TEAM_FILTER_CN = {"solo": "单野", "div": "组队", "div2": "双排", "div3": "三排"}


@dataclass
class Picked:
    rows: list[BattleRow]
    records: list[Record]
    desc: str  # human-readable filter, e.g. "昨天 · 大和 · 随机"
    empty_reason: str = ""  # set when nothing matched


def _period_days(period: tuple | None, today):
    if period is None:
        return None, None
    if period[0] == "ago":
        return today - timedelta(days=period[1]), today - timedelta(days=period[2])

    def resolve(md):
        m, d = md
        for year in (today.year, today.year - 1):
            try:
                day = today.replace(year=year, month=m, day=d)
            except ValueError:
                continue
            if day <= today:
                return day
        return today.replace(year=today.year - 1, month=m, day=min(d, 28))

    a, b = resolve(period[1]), resolve(period[2])  # most recent past occurrence of each date
    return min(a, b), max(a, b)


def period_label(period: tuple | None, today) -> str:
    if period is None:
        return ""
    if period[0] == "ago":
        a, b = period[1], period[2]
        if a == b:
            return {0: "今天", 1: "昨天", 2: "前天"}.get(a, f"{(today - timedelta(days=a)):%m-%d}")
        return f"近 {a + 1} 天" if b == 0 else ""
    start, end = _period_days(period, today)
    return f"{start:%m-%d}" if start == end else f"{start:%m-%d}~{end:%m-%d}"


def _team_match(r: Record, team: str) -> bool:
    if r.mode != "pvp" or not r.division:
        return False
    solo, d2, d3 = r.division
    n = r.stat.battles
    return {"solo": solo, "div": d2 + d3, "div2": d2, "div3": d3}[team] == n


def filter_records(records: list[Record], flt, infos: dict[int, ShipInfo], now: int, *,
                   default_days: int | None = 7) -> Picked:
    today = day_of(now)
    period = flt.period if flt.period is not None else (("ago", default_days - 1, 0) if default_days else None)
    start, end = _period_days(period, today)
    parts = [period_label(period, today) or f"{start:%m-%d}~{end:%m-%d}"] if period else ["全部记录"]
    out = [r for r in records if start is None or start <= day_of(r.captured_at) <= end]
    if flt.ship:
        key = flt.ship.casefold()
        names = {sid: info.name for sid, info in infos.items() if info is not None}
        ids = {sid for sid, name in names.items() if key in name.casefold()}
        out = [r for r in out if r.ship_id in ids]
        matched = sorted({names[r.ship_id] for r in out})
        parts.append(" / ".join(clean(n, 24) for n in matched[:3]) if matched else clean(flt.ship, 24))
    if flt.mode:
        out = [r for r in out if r.mode == flt.mode]
        if not flt.team:
            parts.append(MODE_CN[flt.mode])
    if flt.team:
        out = [r for r in out if _team_match(r, flt.team)]
        parts.append("随机 · " + TEAM_FILTER_CN[flt.team])
    if flt.result:
        out = [r for r in out if (r.stat.wins if flt.result == "win" else r.stat.losses) == r.stat.battles]
        parts.append("胜场" if flt.result == "win" else "负场")
    if flt.sort:
        attr = SORT_ATTR[flt.sort]
        out = sorted(out, key=lambda r: (getattr(r.stat, attr) / r.stat.battles, r.captured_at), reverse=True)
        if flt.sort in ("scouting", "potential"):
            out = [r for r in out if r.full]  # pre-0.2.7 records have no such data
        parts.append(f"按{SORT_CN[flt.sort]}排序")
    reason = ""
    if not out:
        if not records:
            reason = "还没有记录到任何场次"
        elif flt.ship and not any(r.ship_id in {s for s, i in infos.items() if i and flt.ship.casefold() in i.name.casefold()}
                                  for r in records):
            reason = f"记录里没有名字含“{clean(flt.ship, 24)}”的船"
        else:
            reason = "没有符合条件的场次"
    rows = [battle_row(r, infos, with_date=True) for r in out]
    return Picked(rows, out, " · ".join(p for p in parts if p), reason)


def battle_row(r: Record, infos: dict[int, ShipInfo], with_date: bool = False) -> BattleRow:
    name, tname, tier = ship_label(infos.get(r.ship_id), r.ship_id)
    merged_start = fmt_time(r.prev_at) if r.stat.battles > 1 and day_of(r.prev_at) == day_of(r.captured_at) else ""
    row = BattleRow(fmt_time(r.captured_at), merged_start, MODE_CN.get(r.mode, r.mode), name, tname, tier,
                    r.stat, r.career_avg_damage, team_label(r.division))
    if with_date:
        row.date = fmt_time(r.captured_at, "%m-%d")
    return row


@dataclass
class BattlesView:
    who: Identity
    desc: str
    summary: Stat
    base: Stat  # comparison baseline (single ship -> that ship's career, otherwise random career)
    base_label: str
    rows: list[BattleRow]
    groups: list[DayGroup]  # used when not sorted (grouped by day); empty when sorted
    sorted_by: str  # "" or 伤害/击沉/...
    hidden_rows: int
    tracking_since: str
    generated_at: int
    teams: tuple[int, int, int] | None = None


def build_battles(who: Identity, picked: Picked, flt, career: Stat, ship_states: dict, baseline_at: int,
                  now: int, max_rows: int = 15) -> BattlesView:
    recs = picked.records
    summary = sum((r.stat for r in recs), Stat())
    ships = {(r.ship_id, r.mode) for r in recs}
    base, base_label = career, "随机生涯"
    if len({sid for sid, _ in ships}) == 1:
        sid = next(iter(ships))[0]
        mode = "pvp" if (sid, "pvp") in ships else next(iter(ships))[1]
        if (sid, mode) in ship_states:
            base, base_label = ship_states[(sid, mode)], f"{picked.rows[0].ship} {MODE_CN.get(mode, mode)}生涯"
    limit = min(flt.limit or max_rows, max_rows)
    shown_recs, shown_rows = recs[:limit], picked.rows[:limit]
    groups = []
    if not flt.sort:
        by_day: dict = {}
        for r, row in zip(shown_recs, shown_rows):
            row.date = ""
            by_day.setdefault(day_of(r.captured_at), []).append((r, row))
        for d, items in by_day.items():
            label = {day_of(now): "今天", day_of(now) - timedelta(days=1): "昨天"}.get(d, "")
            groups.append(DayGroup(f"{label} {d:%m-%d}".strip(), sum((r.stat for r, _ in items), Stat()),
                                   [row for _, row in items]))
    known = [r.division for r in recs if r.division]
    teams = tuple(sum(d[i] for d in known) for i in range(3)) if known else None
    return BattlesView(who, picked.desc, summary, base, base_label, shown_rows, groups,
                       SORT_CN.get(flt.sort or "", ""), max(len(recs) - limit, 0),
                       fmt_time(baseline_at, "%m-%d %H:%M"), now, teams)


@dataclass
class BattleDetailView:
    who: Identity
    row: BattleRow
    record: Record
    when: str  # 10-15 14:25（或 14:05–14:25 合并）
    ship_career: Stat | None
    history: list[tuple[str, float, bool]]  # (label, per-battle damage, is_this) oldest -> newest
    rank: tuple[int, int] | None  # (rank by damage, out of N) among history
    position: str  # e.g. "今天 · 按伤害排序第 1 / 共 6 场"
    generated_at: int


def build_battle(who: Identity, picked: Picked, index: int, all_records: list[Record], ship_states: dict,
                 now: int, history_size: int = 10) -> BattleDetailView:
    rec, row = picked.records[index], picked.rows[index]
    same = [r for r in all_records if r.ship_id == rec.ship_id and r.mode == rec.mode]
    same = sorted(same, key=lambda r: r.captured_at)
    pos = next((i for i, r in enumerate(same) if r is rec or (r.captured_at, r.stat) == (rec.captured_at, rec.stat)), None)
    if pos is None:
        window = same[-history_size:]
    else:
        lo = max(0, min(pos - history_size // 2, len(same) - history_size))
        window = same[lo:lo + history_size]
    history = [(fmt_time(r.captured_at, "%m-%d"), r.stat.damage / r.stat.battles,
                (r.captured_at, r.stat) == (rec.captured_at, rec.stat)) for r in window]
    rank = None
    if len(history) >= 3 and any(h[2] for h in history):
        mine = rec.stat.damage / rec.stat.battles
        rank = (1 + sum(1 for _, v, this in history if v > mine and not this), len(history))
    if rec.stat.battles > 1 and row.time_end:
        when = f"{fmt_time(rec.captured_at, '%m-%d')} {row.time_end}–{row.time}"
    else:
        when = fmt_time(rec.captured_at, "%m-%d %H:%M")
    position = f"{picked.desc} · 第 {index + 1} / 共 {len(picked.records)} 场"
    return BattleDetailView(who, row, rec, when, ship_states.get((rec.ship_id, rec.mode)), history, rank, position, now)


def state_nomatch(who: Identity, title: str, desc: str, reason: str, baseline_at: int) -> StateView:
    return StateView("idle", title, who, desc, reason,
                     f"只能查到 {fmt_time(baseline_at, '%m-%d %H:%M')} 开始记录之后的场次，条件：{desc}。",
                     "可以换个时间或去掉部分条件再试，例如：/wows 场次 近7天")
