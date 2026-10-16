"""Thin, rate-limited client for the public WG Asia WoWS API (application_id only)."""
import asyncio
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .commands import Query, WowsError

API_BASE = "https://api.worldofwarships.asia/wows/"
# Official clan portal (undocumented, no application_id). Used only for clan-battle league colour.
CLANS_BASE = "https://clans.worldofwarships.asia/api/clanbase/"
LEAGUES = ["飓风", "台风", "风暴", "疾风", "暴风"]
NEUTRAL_CLAN_COLOR = "#B3B3B3"

_STAT = ("battles", "wins", "losses", "draws", "damage_dealt", "frags", "xp", "survived_battles",
         "main_battery.hits", "main_battery.shots")
_MAX = ("max_damage_dealt", "max_damage_dealt_ship_id", "max_frags_battle", "max_frags_ship_id",
        "max_xp", "max_xp_ship_id", "max_damage_scouting", "max_scouting_damage_ship_id")
ACCOUNT_BASE_FIELDS = ("account_id", "nickname", "hidden_profile", "created_at", "last_battle_time",
                       "stats_updated_at")
ACCOUNT_FIELDS = ",".join(
    ACCOUNT_BASE_FIELDS
    + tuple(f"statistics.pvp.{f}" for f in _STAT + _MAX)
    + tuple(f"statistics.rank_solo.{f}" for f in _STAT)
    + tuple(f"statistics.{m}.{f}" for m in ("pvp_solo", "pvp_div2", "pvp_div3") for f in ("battles", "wins"))
)
ACCOUNT_EXTRA = "statistics.rank_solo,statistics.pvp_solo,statistics.pvp_div2,statistics.pvp_div3"
LIGHT_FIELDS = "account_id,nickname,hidden_profile,last_battle_time"
SHIP_FIELDS = ",".join(("ship_id",) + tuple(f"{m}.{f}" for m in ("pvp", "rank_solo") for f in _STAT))
SHIP_EXTRA = "rank_solo"


class ApiRejected(WowsError):
    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


@dataclass
class Resolved:
    account_id: int | None = None
    nickname: str = ""
    candidates: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class ClanInfo:
    clan_id: int
    tag: str
    name: str
    color: str = NEUTRAL_CLAN_COLOR
    league: str = ""  # e.g. "暴风 III"; "" = unknown, "未参加军团战" = no battles this season
    season: int | None = None


@dataclass(frozen=True)
class ShipInfo:
    ship_id: int
    name: str
    tier: int
    type: str


def _chunks(items: list, size: int = 100):
    for i in range(0, len(items), size):
        yield items[i:i + size]


class WowsApi:
    def __init__(self, application_id: str, timeout: float = 15, *,
                 transport: httpx.AsyncBaseTransport | None = None, min_interval: float = 0.25):
        self.application_id = application_id.strip()
        self.timeout = timeout
        self.transport = transport
        self.min_interval = min_interval
        self._next_at = 0.0
        self._rate_lock = asyncio.Lock()
        self._client: httpx.AsyncClient | None = None
        self._ships: dict[int, tuple[float, ShipInfo | None]] = {}
        self._ladder: dict[int, tuple[float, tuple[str, str, int | None] | None]] = {}

    @property
    def configured(self) -> bool:
        return bool(self.application_id)

    def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout, transport=self.transport,
                                             follow_redirects=False)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _wait_turn(self) -> None:
        async with self._rate_lock:
            delay = self._next_at - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            self._next_at = time.monotonic() + self.min_interval

    async def request(self, path: str, **params: Any) -> Any:
        if not self.configured:
            raise WowsError("尚未配置 WG API：请管理员在 .env 中设置 WOWS_APPLICATION_ID 后重启机器人。")
        await self._wait_turn()
        try:
            response = await self._http().get(API_BASE + path, params={
                "application_id": self.application_id, "language": "zh-cn", **params,
            })
            if response.status_code == 429:
                raise WowsError("WG API 请求过于频繁，请稍后再试。")
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException:
            raise WowsError("请求 WG 亚服 API 超时，请稍后再试。") from None
        except httpx.HTTPError:
            raise WowsError("无法访问 WG 亚服 API，请检查机器人服务器的网络或代理配置。") from None
        except ValueError:
            raise WowsError("WG API 返回的内容不是有效 JSON，请稍后再试。") from None
        if not isinstance(payload, dict):
            raise WowsError("WG API 返回格式异常，请稍后再试。")
        if payload.get("status") != "ok":
            error = payload.get("error")
            code = str(error.get("message", "")) if isinstance(error, dict) else ""
            # 错误码要带进提示：原先只特判三类、其余塌缩成同一句话且不写日志，瞬时拒绝无从定位
            if code in {"INVALID_APPLICATION_ID", "APPLICATION_ID_NOT_SPECIFIED", "APPLICATION_IS_BLOCKED"}:
                raise ApiRejected(f"WG application_id 缺失、无效或不可用，请联系管理员检查配置（code={code}）。", code)
            if "LIMIT_EXCEEDED" in code:
                raise ApiRejected(f"WG API 已限制请求频率或额度，请稍后再试（code={code}）。", code)
            raise ApiRejected(
                f"WG API 拒绝了查询（code={code or 'UNKNOWN'}），请稍后重试或联系管理员检查 API 配置。", code
            )
        if "data" not in payload:
            raise WowsError("WG API 返回缺少 data，请稍后再试。")
        return payload["data"]

    async def _request_extra(self, path: str, extra: str, **params: Any) -> Any:
        """Ask with optional `extra`; if WG rejects the extra parameter, retry without it."""
        try:
            return await self.request(path, extra=extra, **params)
        except ApiRejected as exc:
            if "EXTRA" not in exc.code:
                raise
            return await self.request(path, **params)

    # ---- players ----
    async def _search(self, nickname: str, search_type: str) -> list[dict[str, Any]]:
        data = await self.request("account/list/", search=nickname, type=search_type, limit=5,
                                  fields="account_id,nickname")
        if not isinstance(data, list) or any(
            not isinstance(row, dict) or not isinstance(row.get("account_id"), int)
            or row["account_id"] <= 0 or not isinstance(row.get("nickname"), str)
            for row in data
        ):
            raise WowsError("WG 玩家搜索返回格式异常，请稍后再试。")
        return data

    async def resolve(self, query: Query) -> Resolved:
        if query.kind == "id":
            return Resolved(account_id=int(query.value))
        exact = await self._search(query.value, "exact")
        matches = [p for p in exact if p["nickname"].casefold() == query.value.casefold()]
        if len(matches) == 1:
            return Resolved(account_id=matches[0]["account_id"], nickname=matches[0]["nickname"])
        candidates = matches or exact
        if not candidates and len(query.value) >= 3:
            candidates = await self._search(query.value, "startswith")
        return Resolved(candidates=candidates[:5])

    async def account_info(self, account_ids: list[int], *, full: bool = True) -> dict[int, dict | None]:
        out: dict[int, dict | None] = {}
        for chunk in _chunks(list(dict.fromkeys(account_ids))):
            ids = ",".join(map(str, chunk))
            if full:
                data = await self._request_extra("account/info/", ACCOUNT_EXTRA, account_id=ids, fields=ACCOUNT_FIELDS)
            else:
                data = await self.request("account/info/", account_id=ids, fields=LIGHT_FIELDS)
            if not isinstance(data, dict):
                raise WowsError("WG 账号查询返回格式异常，请稍后再试。")
            for aid in chunk:
                value = data.get(str(aid))
                out[aid] = value if isinstance(value, dict) else None
        return out

    async def ship_stats(self, account_id: int) -> list[dict] | None:
        """Per-ship random + ranked totals. None = hidden profile or no data."""
        data = await self._request_extra("ships/stats/", SHIP_EXTRA, account_id=str(account_id), fields=SHIP_FIELDS)
        if not isinstance(data, dict):
            raise WowsError("WG 战舰数据返回格式异常，请稍后再试。")
        ships = data.get(str(account_id))
        if ships is None:
            return None
        if not isinstance(ships, list):
            raise WowsError("WG 战舰数据返回格式异常，请稍后再试。")
        return [s for s in ships if isinstance(s, dict) and isinstance(s.get("ship_id"), int)]

    async def clan_tag(self, account_id: int) -> str:
        info = await self.clan_info(account_id)
        return info.tag if info else ""

    async def clan_info(self, account_id: int) -> ClanInfo | None:
        """Best effort; clan info never blocks a stats card. None = not in a clan (or lookup failed)."""
        try:
            data = await self.request("clans/accountinfo/", account_id=str(account_id), extra="clan",
                                      fields="clan_id,clan.tag,clan.name")
        except WowsError:
            return None
        row = data.get(str(account_id)) if isinstance(data, dict) else None
        clan = row.get("clan") if isinstance(row, dict) else None
        tag = clan.get("tag") if isinstance(clan, dict) else None
        if not isinstance(tag, str) or not tag:
            return None
        clan_id = row.get("clan_id")
        name = clan.get("name") if isinstance(clan.get("name"), str) else ""
        if not isinstance(clan_id, int) or clan_id <= 0:
            return ClanInfo(0, tag, name)
        ladder = await self.clan_ladder(clan_id)
        if ladder is None:
            return ClanInfo(clan_id, tag, name)
        color, league, season = ladder
        return ClanInfo(clan_id, tag, name, color, league, season)

    async def clan_ladder(self, clan_id: int, ttl: float = 3600) -> tuple[str, str, int | None] | None:
        """(hex colour, league label, season) from the official clan portal; cached, failures -> None."""
        now = time.monotonic()
        hit = self._ladder.get(clan_id)
        if hit and hit[0] > now:
            return hit[1]
        result = None
        try:
            await self._wait_turn()
            response = await self._http().get(f"{CLANS_BASE}{clan_id}/claninfo/")
            payload = response.json() if response.status_code == 200 else None
            view = payload.get("clanview", payload) if isinstance(payload, dict) else None
            ladder = view.get("wows_ladder") if isinstance(view, dict) else None
            clan = view.get("clan") if isinstance(view, dict) else None
            if isinstance(ladder, dict):
                # clan.color is the in-game tag colour; wows_ladder.color is not (often neutral grey).
                color = (clan.get("color") if isinstance(clan, dict) else None) or ladder.get("color")
                color = color.upper() if isinstance(color, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", color) \
                    else NEUTRAL_CLAN_COLOR
                season = ladder.get("season_number") if isinstance(ladder.get("season_number"), int) else None
                league, division = ladder.get("league"), ladder.get("division")
                if not ladder.get("battles_count"):
                    result = (NEUTRAL_CLAN_COLOR, "未参加军团战", season)
                elif isinstance(league, int) and 0 <= league < len(LEAGUES):
                    label = LEAGUES[league]
                    if league > 0 and isinstance(division, int) and 1 <= division <= 3:
                        label += " " + "I" * division
                    result = (color, label, season)
                else:
                    result = (color, "", season)
        except (httpx.HTTPError, ValueError):
            result = None
        self._ladder[clan_id] = (now + (ttl if result else 300), result)
        return result

    async def ships_info(self, ship_ids: list[int], ttl: float = 86400) -> dict[int, ShipInfo]:
        now = time.monotonic()
        missing = [i for i in dict.fromkeys(ship_ids) if i not in self._ships or self._ships[i][0] <= now]
        for chunk in _chunks(missing):
            try:
                data = await self.request("encyclopedia/ships/", ship_id=",".join(map(str, chunk)),
                                          fields="ship_id,name,tier,type")
            except WowsError:
                break  # names are cosmetic; fall back to IDs
            for sid in chunk:
                row = data.get(str(sid)) if isinstance(data, dict) else None
                info = None
                if isinstance(row, dict) and isinstance(row.get("name"), str):
                    tier = row.get("tier") if isinstance(row.get("tier"), int) else 0
                    info = ShipInfo(sid, row["name"], tier, str(row.get("type") or ""))
                self._ships[sid] = (now + ttl, info)
        out = {}
        for sid in ship_ids:
            entry = self._ships.get(sid)
            if entry and entry[1] is not None:
                out[sid] = entry[1]
        return out
