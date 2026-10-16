from dataclasses import dataclass

HELP = """WoWS 亚服战绩查询
/wows 玩家昵称　　查总战绩卡
/wows id 账号ID　 按账号 ID 查询
/wows 绑定 昵称　 绑定自己的账号（也可 绑定 id 账号ID）
/wows　　　　　　 查自己（需先绑定）
/wows 最近 [昵称]　最近 7 天汇总 + 最近两天场次
/wows 解绑　　　　取消绑定
别名：/窝窝战绩
最近战绩依靠定时记录战绩快照得出：绑定或首次查询后开始记录，之前的场次查不到。
指令前缀以机器人的 COMMAND_START 配置为准。"""

RECENT_WORDS = {"最近", "近期", "recent", "最近战绩"}
BIND_WORDS = {"绑定", "bind"}
UNBIND_WORDS = {"解绑", "unbind"}
SELF_WORDS = {"我", "me"}
HELP_WORDS = {"help", "--help", "帮助"}


class WowsError(Exception):
    """A safe, user-facing error (never contains request URLs or credentials)."""


@dataclass(frozen=True)
class Query:
    kind: str  # "name" | "id"
    value: str


@dataclass(frozen=True)
class Command:
    action: str  # help | total | recent | bind | unbind
    target: Query | None = None  # None = the caller's bound account


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
    if len(parts) == 1 and head in SELF_WORDS:
        return Command("total")
    return Command("total", _target(parts))
