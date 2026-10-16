"""Command orchestration, independent from NoneBot so it can be tested directly."""
import time
from dataclasses import dataclass
from typing import Union

from . import cards, formatting, views
from .api import WowsApi
from .commands import HELP, Command, Query, WowsError, parse_command
from .renderer import CardRenderer
from .stats import num
from .storage import Storage
from .tracker import Tracker

Reply = Union[str, bytes]


@dataclass
class Card:
    html: str
    text: str


class WowsApp:
    def __init__(self, api: WowsApi, storage: Storage, renderer: CardRenderer | None, *,
                 tracker: Tracker, cache_seconds: int = 60, min_battles: int = 50, poll_minutes: int = 10,
                 clock=time.time, logger=None):
        self.api = api
        self.storage = storage
        self.renderer = renderer
        self.tracker = tracker
        self.cache_seconds = cache_seconds
        self.min_battles = min_battles
        self.poll_minutes = poll_minutes
        self.clock = clock
        self.logger = logger
        self._cache: dict[int, tuple[float, dict]] = {}

    def now(self) -> int:
        return int(self.clock())

    async def handle(self, user_key: str | None, raw: str) -> Reply:
        try:
            cmd = parse_command(raw)
            if cmd.action == "help":
                return HELP
            if cmd.action == "unbind":
                return self._unbind(user_key)
            if cmd.action == "bind":
                return await self._bind(user_key, cmd.target)
            account_id, reply = await self._target(user_key, cmd)
            if reply is not None:
                return reply
            card = await (self.recent_card(account_id) if cmd.action == "recent" else self.total_card(account_id))
            return await self._output(card)
        except WowsError as exc:
            if self.logger:
                # 只记类型与错误码，不回显异常文本（可能含请求 URL / application_id）
                code = getattr(exc, "code", "") or "-"
                self.logger.warning(f"WoWS command failed: {type(exc).__name__} code={code}")
            return str(exc)
        except Exception as exc:
            # Do not log request objects/URLs or echo exception text containing app IDs.
            if self.logger:
                self.logger.error(f"WoWS command failed unexpectedly: {type(exc).__name__}")
            return "战绩查询遇到内部错误，请联系管理员检查插件环境。"

    async def _output(self, card: Card) -> Reply:
        if self.renderer is None:
            return card.text
        try:
            return await self.renderer.render(card.html)
        except Exception as exc:
            if self.logger:
                self.logger.warning(f"WoWS card render failed, falling back to text: {type(exc).__name__}: {exc}")
            return card.text

    # ---- targets / binding ----
    async def _target(self, user_key: str | None, cmd: Command) -> tuple[int, Reply | None]:
        if cmd.target is None:
            bound = self.storage.binding(user_key) if user_key else None
            if bound is None:
                if cmd.action == "total":
                    return 0, HELP
                return 0, "你还没有绑定账号：先用 /wows 绑定 你的昵称，或使用 /wows 最近 玩家昵称。"
            return bound[0], None
        return await self._resolve(cmd.target)

    async def _resolve(self, query: Query) -> tuple[int, Reply | None]:
        resolved = await self.api.resolve(query)
        if resolved.account_id is None:
            return 0, formatting.candidates_text(resolved.candidates or [])
        return resolved.account_id, None

    def _unbind(self, user_key: str | None) -> str:
        if not user_key:
            return "当前消息无法识别用户，不能解绑。"
        return "已解除绑定。" if self.storage.unbind(user_key) else "你还没有绑定账号。"

    async def _bind(self, user_key: str | None, query: Query) -> str:
        if not user_key:
            return "当前消息无法识别用户，不能绑定。"
        account_id, reply = await self._resolve(query)
        if reply is not None:
            return reply if isinstance(reply, str) else "绑定失败。"
        account = await self._account(account_id)
        nickname = views.clean(account.get("nickname") or account_id)
        self.storage.bind(user_key, account_id, nickname, self.now())
        self.tracker.touch(account_id, nickname)
        msg = f"已绑定：{nickname}（{account_id}）。"
        if account.get("hidden_profile") is True:
            return msg + "\n该账号隐藏了战绩，公开战绩后才能记录最近战绩。"
        await self.tracker.refresh(account_id, last_battle_time=num(account.get("last_battle_time")))
        return msg + "\n已开始记录战绩快照，之后打的每一场都会出现在 /wows 最近 里。"

    # ---- data ----
    async def _account(self, account_id: int) -> dict:
        hit = self._cache.get(account_id)
        if hit and hit[0] > time.monotonic():
            return hit[1]
        data = (await self.api.account_info([account_id], full=True)).get(account_id)
        if data is None:
            raise WowsError("亚服没有找到这个账号，或该账号没有可查询的 WoWS 资料。")
        if self.cache_seconds > 0:
            self._cache[account_id] = (time.monotonic() + self.cache_seconds, data)
            if len(self._cache) > 256:
                self._cache.pop(next(iter(self._cache)))
        return data

    async def _identity(self, account_id: int, account: dict) -> views.Identity:
        nickname = views.clean(account.get("nickname") or account_id, 32)
        clan = await self.api.clan_info(account_id)
        if clan is None:
            return views.Identity(account_id, nickname)
        return views.Identity(account_id, nickname, views.clean(clan.tag, 8), views.clean(clan.name, 40),
                              clan.color, views.clean(clan.league, 16))

    def _state(self, state: views.StateView) -> Card:
        return Card(cards.state_html(state, self.now()), formatting.state_text(state))

    async def total_card(self, account_id: int) -> Card:
        account = await self._account(account_id)
        who = await self._identity(account_id, account)
        if account.get("hidden_profile") is True:
            return self._state(views.state_hidden(who, "总战绩"))
        random = views.career_random(account)
        if random.battles < max(self.min_battles, 1):
            return self._state(views.state_newbie(who, random, self.min_battles))
        ships = await self.api.ship_stats(account_id)
        if ships is None:
            return self._state(views.state_hidden(who, "总战绩"))
        infos = await self.api.ships_info(views.total_ship_ids(account, ships))
        view = views.build_total(who, account, ships, infos, self.now())
        return Card(cards.total_html(view), formatting.total_text(view))

    async def recent_card(self, account_id: int) -> Card:
        account = await self._account(account_id)
        who = await self._identity(account_id, account)
        if account.get("hidden_profile") is True:
            return self._state(views.state_hidden(who, "最近战绩"))
        if not self.tracker.touch(account_id, who.nickname):
            return self._state(views.state_quota(who))
        result = await self.tracker.refresh(account_id, last_battle_time=num(account.get("last_battle_time")))
        if result.hidden:
            return self._state(views.state_hidden(who, "最近战绩"))
        tracked = self.storage.tracked(account_id)
        now = self.now()
        baseline = tracked.baseline_at if tracked and tracked.baseline_at else now
        records = self.storage.records(account_id, now - 15 * 86400)
        start7 = views.day_of(now).toordinal() - 6
        if not any(views.day_of(r.captured_at).toordinal() >= start7 for r in records):
            if result.baseline_created or now - baseline < 86400:
                return self._state(views.state_tracking(who, baseline, self.poll_minutes))
            return self._state(views.state_idle(who, baseline))
        infos = await self.api.ships_info(list({r.ship_id for r in records}))
        view = views.build_recent(who, views.career_random(account), records, infos, baseline, now)
        return Card(cards.recent_html(view), formatting.recent_text(view))
