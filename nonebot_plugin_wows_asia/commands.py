import re
from dataclasses import dataclass
from datetime import date as calendar_date

HELP = """WoWS 亚服战绩查询
/wows 玩家昵称　　查总战绩卡
/wows id 账号ID　 按账号 ID 查询
/wows 绑定 昵称　 绑定自己的账号（也可 绑定 id 账号ID）
/wows　　　　　　 查自己（需先绑定）
/wows 最近 [昵称]　最近 7 天汇总 + 最近两天场次
/wows 场次 [谁] [筛选]　按条件列出记录到的场次
/wows 单场 [谁] [筛选|序号]　单场详情（默认最近一场）
　谁：我（默认）/ 昵称 / id 账号ID / @某人
　筛选（顺序随意）：今天 昨天 前天 近3天 10-15 10-12~10-15
　　上午 下午 晚上 凌晨（可连写：今天下午）　14点后 14-18点
　　船=大和　随机 排位 单野 组队 双排 三排　胜 负
　　按伤害 按击沉 按经验 按侦察 按潜在（伤害最低 = 从低到高）
　　最好 最差（按经验）　前5
　例：/wows 单场 今天 按伤害　/wows 场次 昨天 船=大和　/wows 场次 最差5把
/wows 解绑　　　　取消绑定
别名：/窝窝战绩
最近战绩依靠定时记录战绩快照得出：绑定或首次查询后开始记录，之前的场次查不到。
指令前缀以机器人的 COMMAND_START 配置为准。"""

RECENT_WORDS = {"最近", "近期", "recent", "最近战绩"}
BIND_WORDS = {"绑定", "bind"}
UNBIND_WORDS = {"解绑", "unbind"}
SELF_WORDS = {"我", "me"}
BATTLES_WORDS = {"场次", "战斗", "battles"}
BATTLE_WORDS = {"单场", "battle"}
HELP_WORDS = {"help", "--help", "帮助"}


class WowsError(Exception):
    """A safe, user-facing error (never contains request URLs or credentials)."""


@dataclass(frozen=True)
class Query:
    kind: str  # "name" | "id"
    value: str


@dataclass(frozen=True)
class Filter:
    """Battle-record filter for 场次 / 单场. Dates are resolved against "now" later (views.filter_records)."""
    period: tuple | None = None  # ("ago", from_days_ago, to_days_ago) | ("date", (m, d), (m, d))
    hours: tuple[int, int] | None = None  # time of day [start, end) in UTC+8, e.g. (12, 18) = 下午
    ship: str | None = None  # substring of the ship name
    mode: str | None = None  # pvp | rank_solo
    team: str | None = None  # solo | div | div2 | div3 (random only)
    result: str | None = None  # win | loss
    sort: str | None = None  # damage | frags | xp | scouting | potential; None = newest first
    asc: bool = False  # sort lowest first (伤害最低 / 最差)
    limit: int | None = None
    index: int | None = None  # 单场 N: the N-th entry of the (sorted) list


@dataclass(frozen=True)
class Command:
    action: str  # help | total | recent | bind | unbind | battles | battle
    target: Query | None = None  # None = the caller's bound account (or the @mentioned user's)
    filter: Filter | None = None


FILTER_USAGE = ("筛选写法：今天 / 昨天 / 前天 / 近3天 / 10-15 / 10-12~10-15，上午 / 下午 / 晚上 / 凌晨 / 14点后 / 14-18点，船=船名，随机 / 排位 / 单野 / 组队 / 双排 / 三排，"
                "胜 / 负，按伤害 / 按击沉 / 按经验 / 按侦察 / 按潜在（伤害最低 等为从低到高），最好 / 最差（按经验），前N。"
                "例：/wows 场次 昨天 船=大和")
_DAY_WORDS = {"今天": 0, "今日": 0, "昨天": 1, "昨日": 1, "前天": 2}
_HOUR_WORDS = {"凌晨": (0, 6), "半夜": (0, 6), "深夜": (0, 6), "早上": (6, 12), "上午": (6, 12), "中午": (11, 13),
               "下午": (12, 18), "傍晚": (17, 19), "晚上": (18, 24), "晚间": (18, 24), "夜里": (18, 24)}
HOURS_CN = {(0, 6): "凌晨", (6, 12): "上午", (11, 13): "中午", (12, 18): "下午", (17, 19): "傍晚", (18, 24): "晚上"}
_PART_OF_DAY = re.compile(r"(今天|今日|昨天|昨日|前天)?(" + "|".join(_HOUR_WORDS) + ")")
_WEEK_WORDS = {"本周", "这周", "一周", "近一周", "最近一周", "这一周"}
_MODE_WORDS = {"随机": ("pvp", None), "随机战": ("pvp", None), "随机战斗": ("pvp", None),
               "排位": ("rank_solo", None), "排位赛": ("rank_solo", None),
               "单野": ("pvp", "solo"), "单排": ("pvp", "solo"), "组队": ("pvp", "div"), "开黑": ("pvp", "div"),
               "双排": ("pvp", "div2"), "三排": ("pvp", "div3")}
_RESULT_WORDS = {"胜": "win", "赢": "win", "胜场": "win", "赢的": "win", "负": "loss", "输": "loss", "败": "loss",
                 "负场": "loss", "输的": "loss"}
_SORT_WORDS = {"伤害": "damage", "击沉": "frags", "经验": "xp", "侦察": "scouting", "侦察伤害": "scouting",
               "潜在": "potential", "潜在伤害": "potential"}
_DATE = r"(\d{1,2})[-/.月](\d{1,2})日?"


_HIGH, _LOW = "(?:最高|最多)", "(?:最低|最少)"
# 最好 / 最差 rank by XP: it rewards damage, kills, caps and spotting alike, so it compares across ship types
_BEST = re.compile(r"(?:打得?)?最(好|差|烂)(?:的)?(?:(\d{1,2})(?:场|把|局)?)?")


def _sort_word(token: str) -> tuple[str, bool] | None:
    """按伤害 / 伤害最高 / 最高伤害 -> (sort, False); 伤害最低 / 最少击沉 -> (sort, True)."""
    for pattern, asc in ((r"按(.+)", False), (rf"(.+?){_HIGH}", False), (rf"{_HIGH}(.+)", False),
                         (rf"(.+?){_LOW}", True), (rf"{_LOW}(.+)", True)):
        m = re.fullmatch(pattern, token)
        if m and m.group(1) in _SORT_WORDS:
            return _SORT_WORDS[m.group(1)], asc
    return None


def _date(m: str, d: str) -> tuple[int, int]:
    month, day = int(m), int(d)
    if not (1 <= month <= 12 and 1 <= day <= 31):
        raise WowsError(f"日期 {m}-{d} 无效。" + FILTER_USAGE)
    try:
        calendar_date(2000, month, day)  # leap year keeps 02-29 valid for historical queries
    except ValueError:
        raise WowsError(f"日期 {m}-{d} 无效。" + FILTER_USAGE) from None
    return month, day


def _parse_filter(parts: list[str], allow_index: bool) -> tuple[Filter, Query | None]:
    f: dict = {}
    leftover: list[str] = []
    target = None

    def put(key: str, value) -> None:
        if f.get(key) not in (None, value):
            raise WowsError("筛选条件互相冲突，请只写一个时间 / 模式 / 排序（最高和最低也只能选一个）。" + FILTER_USAGE)
        f[key] = value

    i = 0
    while i < len(parts):
        tok = parts[i]
        low = tok.lower()
        i += 1
        if low in SELF_WORDS:
            continue
        if low == "id" and i < len(parts):
            target = _target(["id", parts[i]])
            i += 1
            continue
        if tok in _DAY_WORDS:
            put("period", ("ago", _DAY_WORDS[tok], _DAY_WORDS[tok]))
        elif m := _PART_OF_DAY.fullmatch(tok):
            if m.group(1):
                put("period", ("ago", _DAY_WORDS[m.group(1)], _DAY_WORDS[m.group(1)]))
            put("hours", _HOUR_WORDS[m.group(2)])
        elif m := re.fullmatch(r"(\d{1,2})(?:点|时)(以后|之后|后|以前|之前|前)", tok):
            h = int(m.group(1))
            if not 1 <= h <= 23:
                raise WowsError("钟点请写 1～23 点，例如：14点后")
            put("hours", (h, 24) if "后" in m.group(2) else (0, h))
        elif m := re.fullmatch(r"(\d{1,2})(?:点|时)?(?:-|~|～|到|至)(\d{1,2})(?:点|时)", tok):
            a, b = int(m.group(1)), int(m.group(2))
            if not 0 <= a < b <= 24:
                raise WowsError("时段请写成 开始点-结束点，例如：14-18点")
            put("hours", (a, b))
        elif tok in _WEEK_WORDS:
            put("period", ("ago", 6, 0))
        elif m := re.fullmatch(r"(?:近|最近)(\d{1,3})(?:天|日)", tok):
            n = int(m.group(1))
            if not 1 <= n <= 90:
                raise WowsError("“近N天”的 N 需在 1～90 之间。")
            put("period", ("ago", n - 1, 0))
        elif m := re.fullmatch(_DATE + r"(?:~|～|至|到|--)" + _DATE, tok):
            put("period", ("date", _date(m.group(1), m.group(2)), _date(m.group(3), m.group(4))))
        elif m := re.fullmatch(_DATE, tok):
            d = _date(m.group(1), m.group(2))
            put("period", ("date", d, d))
        elif m := re.fullmatch(r"(?:船|ship|战舰)[=:：](.+)", tok, re.I):
            name = m.group(1).strip()
            if not 1 <= len(name) <= 24:
                raise WowsError("船名请写 1～24 个字，例如：船=大和")
            put("ship", name)
        elif tok in _MODE_WORDS:
            mode, team = _MODE_WORDS[tok]
            put("mode", mode)
            if team:
                put("team", team)
        elif tok in _RESULT_WORDS:
            put("result", _RESULT_WORDS[tok])
        elif sort := _sort_word(tok):
            put("sort", sort[0])
            put("asc", sort[1])
        elif m := _BEST.fullmatch(tok):
            put("sort", "xp")
            put("asc", m.group(1) != "好")
            if m.group(2):
                put("limit", int(m.group(2)))
        elif tok in ("按时间", "最新", "最近"):
            continue
        elif m := re.fullmatch(r"(?:前|最多)?(\d{1,2})(?:场|把|局)|前(\d{1,2})", tok):
            put("limit", int(m.group(1) or m.group(2)))
        elif allow_index and (m := re.fullmatch(r"(?:倒数)?第?(\d{1,2})(?:场|把|局)?", tok)):
            put("index", int(m.group(1)))
        else:
            leftover.append(tok)
    if leftover:
        if target is not None or len(leftover) > 1:
            raise WowsError(f"看不懂“{' '.join(leftover)}”。" + FILTER_USAGE)
        target = _target(leftover)
    if allow_index and f.get("limit") and not f.get("index"):
        f["index"], f["limit"] = f.pop("limit"), None  # “单场 3场” reads as the 3rd one
    if f.get("hours") and not f.get("period"):
        f["period"] = ("ago", 0, 0)  # “下午” alone means this afternoon
    if f.get("index") == 0 or f.get("limit") == 0:
        raise WowsError("序号和数量从 1 开始。")
    return Filter(**f), target


def _target(parts: list[str]) -> Query:
    if len(parts) == 2 and parts[0].lower() == "id":
        value = parts[1]
        if not 1 <= len(value) <= 19 or not value.isascii() or not value.isdecimal() or not 0 < int(value) <= 2**63 - 1:
            raise WowsError("账号 ID 必须是有效的正整数，例如：/wows id 2000000001")
        return Query("id", str(int(value)))
    if len(parts) != 1:
        raise WowsError("用法：/wows 完整昵称，或 /wows id 账号ID")
    nickname = parts[0]
    if not 1 <= len(nickname) <= 24 or "," in nickname or any(ord(c) < 32 for c in nickname):
        raise WowsError("请输入 1～24 个字符的单个玩家昵称，不要带逗号或控制字符。")
    # All-digit nicknames are still nicknames; only 'id N' selects an account ID.
    return Query("name", nickname)


def parse_query(raw: str) -> Query | None:
    """Parse a plain player target. None means help."""
    parts = raw.strip().split()
    if not parts or (len(parts) == 1 and parts[0].lower() in HELP_WORDS):
        return None
    return _target(parts)


def parse_command(raw: str) -> Command:
    parts = raw.strip().split()
    if not parts:
        return Command("total")
    head = parts[0].lower()
    rest = parts[1:]
    if len(parts) == 1 and head in HELP_WORDS:
        return Command("help")
    if head in UNBIND_WORDS:
        if rest:
            raise WowsError("用法：/wows 解绑")
        return Command("unbind")
    if head in BIND_WORDS:
        if not rest:
            raise WowsError("用法：/wows 绑定 完整昵称，或 /wows 绑定 id 账号ID")
        return Command("bind", _target(rest))
    if head in RECENT_WORDS:
        if not rest or (len(rest) == 1 and rest[0].lower() in SELF_WORDS):
            return Command("recent")
        return Command("recent", _target(rest))
    if head in BATTLES_WORDS or head in BATTLE_WORDS:
        single = head in BATTLE_WORDS
        flt, target = _parse_filter(rest, allow_index=single)
        return Command("battle" if single else "battles", target, flt)
    if len(parts) == 1 and head in SELF_WORDS:
        return Command("total")
    return Command("total", _target(parts))
