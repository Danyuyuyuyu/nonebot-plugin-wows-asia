import os
import shutil

import httpx
import pytest

from nonebot_plugin_wows_asia import cards, views
from nonebot_plugin_wows_asia.api import ACCOUNT_FIELDS, ApiRejected, WowsApi
from nonebot_plugin_wows_asia.app import WowsApp
from nonebot_plugin_wows_asia.commands import Command, Query, WowsError, parse_command, parse_query
from nonebot_plugin_wows_asia.renderer import CardRenderer
from nonebot_plugin_wows_asia.stats import Stat, ship_states
from nonebot_plugin_wows_asia.storage import Storage
from nonebot_plugin_wows_asia.tracker import Tracker, diff_states

from .fakes import AID, Clock, FakeWG, make_api

USER = "OneBot V11:10001"


# ---------------- commands ----------------
@pytest.mark.parametrize("raw,expected", [
    ("", Command("total")),
    ("help", Command("help")),
    ("帮助", Command("help")),
    ("我", Command("total")),
    ("Example_Player", Command("total", Query("name", "Example_Player"))),
    ("id 2000000001", Command("total", Query("id", "2000000001"))),
    ("12345", Command("total", Query("name", "12345"))),
    ("最近", Command("recent")),
    ("最近 我", Command("recent")),
    ("recent Foo", Command("recent", Query("name", "Foo"))),
    ("近期 id 7", Command("recent", Query("id", "7"))),
    ("绑定 Foo", Command("bind", Query("name", "Foo"))),
    ("bind id 0042", Command("bind", Query("id", "42"))),
    ("解绑", Command("unbind")),
])
def test_parse_command(raw, expected):
    assert parse_command(raw) == expected


@pytest.mark.parametrize("raw", ["绑定", "解绑 x", "a b", "id 0", "id -1", "id 99999999999999999999", "a,b", "x" * 25,
                                 "id １２"])
def test_parse_command_errors(raw):
    with pytest.raises(WowsError):
        parse_command(raw)


def test_parse_query_compat():
    assert parse_query("") is None and parse_query("help") is None
    assert parse_query("id 5") == Query("id", "5")


# ---------------- api ----------------
async def test_api_params_and_hidden():
    fake = FakeWG()
    api = make_api(fake)
    data = await api.account_info([AID, AID, 3])
    assert data[AID]["nickname"] == "Example_Player" and data[3] is None
    path, params = fake.calls[-1]
    assert path == "account/info/" and params["account_id"] == f"{AID},3"
    assert params["fields"] == ACCOUNT_FIELDS and "extra" in params and params["language"] == "zh-cn"
    assert params["application_id"] == "test-application-id"
    fake.account = {"account_id": AID, "nickname": "X", "hidden_profile": True, "last_battle_time": 1}
    assert await api.ship_stats(AID) is None
    await api.close()


async def test_api_extra_fallback():
    fake = FakeWG()
    fake.reject_extra = True
    api = make_api(fake)
    data = await api.account_info([AID])
    assert data[AID] is not None
    assert [("extra" in p) for path, p in fake.calls] == [True, False]
    ships = await api.ship_stats(AID)
    assert len(ships) == 4
    await api.close()


async def test_api_batches_of_100():
    fake = FakeWG()
    api = make_api(fake)
    await api.account_info(list(range(1, 251)), full=False)
    assert [len(p["account_id"].split(",")) for _, p in fake.calls] == [100, 100, 50]
    assert "extra" not in fake.calls[0][1]


@pytest.mark.parametrize("payload,status,expected", [
    ({"status": "error", "error": {"message": "INVALID_APPLICATION_ID"}}, 200, "application_id"),
    ({"status": "error", "error": {"message": "REQUEST_LIMIT_EXCEEDED"}}, 200, "频率"),
    ({"status": "error", "error": {"message": "SOMETHING"}}, 200, "拒绝"),
    ({"status": "ok"}, 200, "缺少 data"),
    (None, 429, "过于频繁"),
    (None, 500, "无法访问"),
])
async def test_api_errors(payload, status, expected):
    def handler(request):
        return httpx.Response(status, json=payload) if payload is not None else httpx.Response(status)
    api = WowsApi("secret-app-id", transport=httpx.MockTransport(handler), min_interval=0)
    with pytest.raises(WowsError) as info:
        await api.request("account/list/")
    assert expected in str(info.value) and "secret-app-id" not in str(info.value)


async def test_api_timeout_and_unconfigured():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)
    api = WowsApi("k", transport=httpx.MockTransport(handler), min_interval=0)
    with pytest.raises(WowsError, match="超时"):
        await api.request("x/")
    with pytest.raises(WowsError, match="WOWS_APPLICATION_ID"):
        await WowsApi("  ").request("x/")


async def test_resolve_exact_candidates_and_id():
    fake = FakeWG()
    api = make_api(fake)
    assert (await api.resolve(Query("name", "example_player"))).account_id == AID
    fake.search = [{"account_id": 1, "nickname": "Ab"}, {"account_id": 2, "nickname": "Abc"}]
    r = await api.resolve(Query("name", "Abx"))
    assert r.account_id is None and len(r.candidates) == 2
    assert (await api.resolve(Query("id", "9"))).account_id == 9
    fake.search = [{"account_id": "bad", "nickname": 1}]
    with pytest.raises(WowsError, match="格式异常"):
        await api.resolve(Query("name", "Abx"))


async def test_ships_info_cache_and_clan():
    fake = FakeWG()
    api = make_api(fake)
    infos = await api.ships_info([1, 2, 99])
    assert infos[1].name == "大和" and 99 not in infos
    n = len(fake.calls)
    await api.ships_info([1, 2, 99])
    assert len(fake.calls) == n
    assert await api.clan_tag(AID) == "NYAN"
    fake.clan = None
    assert await api.clan_tag(AID) == ""


# ---------------- diff ----------------
def S(**kw):
    return Stat(**kw)


def test_diff_single_merged_anomaly_new_ship():
    old = {(1, "pvp"): S(battles=10, wins=5, losses=5, damage=500000), (2, "pvp"): S(battles=5, wins=2, losses=3)}
    new = {(1, "pvp"): S(battles=12, wins=7, losses=5, damage=650000),  # two merged battles
           (2, "pvp"): S(battles=4, wins=2, losses=2),  # decreased: anomaly -> rebaseline
           (3, "rank_solo"): S(battles=1, wins=0, losses=1, damage=30000)}  # new ship
    deltas, changed = diff_states(old, new)
    by = {k: (d, c) for k, d, c in deltas}
    assert set(by) == {(1, "pvp"), (3, "rank_solo")}
    assert by[(1, "pvp")][0].battles == 2 and by[(1, "pvp")][0].damage == 150000 and by[(1, "pvp")][1] == 50000
    assert by[(3, "rank_solo")][1] is None
    assert set(changed) == set(new)
    # wins jumping more than battles is inconsistent -> no record
    deltas, _ = diff_states({(1, "pvp"): S(battles=1)}, {(1, "pvp"): S(battles=2, wins=3)})
    assert deltas == []


def test_ship_states_modes():
    fake = FakeWG()
    states = ship_states(fake.ships)
    assert (1, "pvp") in states and (1, "rank_solo") in states and (2, "rank_solo") not in states


# ---------------- tracker ----------------
def make_env(**app_kw):
    fake = FakeWG()
    clock = Clock()
    api = make_api(fake)
    storage = Storage(":memory:")
    tracker = Tracker(api, storage, clock=clock, max_tracked=app_kw.pop("max_tracked", 200))
    app = WowsApp(api, storage, app_kw.pop("renderer", None), tracker=tracker, cache_seconds=0, clock=clock,
                  **app_kw)
    return fake, clock, storage, tracker, app


async def test_tracker_baseline_records_and_retry():
    fake, clock, storage, tracker, _ = make_env()
    assert tracker.touch(AID, "Example_Player")
    lbt = fake.account["last_battle_time"]
    r = await tracker.refresh(AID, last_battle_time=lbt)
    assert r.baseline_created and storage.tracked(AID).baseline_at == clock.t
    clock.t += 30
    assert (await tracker.refresh(AID, last_battle_time=lbt + 10)).skipped  # 60s gap
    clock.t += 600
    assert (await tracker.refresh(AID, last_battle_time=lbt)).skipped  # nothing new
    fake.play(1, dmg=120000)
    fake.play(1, w=0, l=1, dmg=80000, sv=0)
    r = await tracker.refresh(AID, last_battle_time=fake.account["last_battle_time"])
    assert r.new_records == 1
    rec = storage.records(AID, 0)[0]
    assert rec.stat.battles == 2 and rec.stat.damage == 200000 and rec.career_avg_damage == pytest.approx(96500)
    # WG bumped last_battle_time but ship stats lag: marker not advanced so the next poll retries
    clock.t += 600
    fake.account["last_battle_time"] = clock.t - 60
    r = await tracker.refresh(AID, last_battle_time=fake.account["last_battle_time"])
    assert r.new_records == 0 and storage.tracked(AID).last_battle_time < fake.account["last_battle_time"]


async def test_poll_all_and_prune():
    fake, clock, storage, tracker, _ = make_env()
    tracker.touch(AID, "Example_Player")
    tracker.touch(42, "Ghost")  # unknown to WG -> skipped
    assert await tracker.poll_all() == 0  # creates baseline for AID
    assert storage.tracked(AID).baseline_at is not None
    clock.t += 600
    fake.play(3, mode="rank_solo", dmg=50000)
    fake.play(2)
    assert await tracker.poll_all() == 2
    calls = [p for p, _ in fake.calls]
    assert calls.count("ships/stats/") == 2
    clock.t += 600
    n = len(fake.calls)
    assert await tracker.poll_all() == 0
    assert [p for p, _ in fake.calls[n:]] == ["account/info/"]  # no ship fetch without new battles
    clock.t += 15 * 86400
    assert set(tracker.prune()) == {AID, 42}


async def test_tracker_quota_bound_exempt():
    fake, clock, storage, tracker, _ = make_env(max_tracked=1)
    assert tracker.touch(1, "a")
    assert not tracker.touch(AID, "b")
    storage.bind(USER, AID, "b", clock.t)
    assert tracker.touch(AID, "b")


# ---------------- app flows ----------------
async def test_total_text_and_help():
    fake, clock, storage, tracker, app = make_env()
    assert "/wows 绑定" in await app.handle(USER, "")
    text = await app.handle(USER, "Example_Player")
    assert "[NYAN]Example_Player" in text and "1,000 场" in text and "55.00%" in text
    assert "排位" in text and "287,640" in text and "大和" in text


async def test_total_newbie_hidden_candidates():
    fake, clock, storage, tracker, app = make_env()
    from .fakes import account
    fake.account = account(battles=12)
    assert "场数还比较少" in await app.handle(USER, "Example_Player")
    fake.account = account(hidden=True)
    assert "隐藏了战绩" in await app.handle(USER, "Example_Player")
    fake.search = []
    assert "未找到" in await app.handle(USER, "Nobody")
    fake.search = [{"account_id": 7, "nickname": "Nob"}, {"account_id": 8, "nickname": "Nobb"}]
    out = await app.handle(USER, "Nobx")
    assert "/wows id 7" in out and "/wows id 8" in out


async def test_bind_recent_flow():
    fake, clock, storage, tracker, app = make_env()
    assert "还没有绑定" in await app.handle(USER, "最近")
    assert "已绑定：Example_Player" in await app.handle(USER, "绑定 Example_Player")
    assert storage.binding(USER)[0] == AID and storage.tracked(AID).baseline_at is not None
    clock.t += 120
    assert "还没有足够的近期数据" in await app.handle(USER, "最近")
    clock.t += 600
    fake.play(1, dmg=150000, fr=3)
    out = await app.handle(USER, "最近")
    assert "【最近战绩" in out and "胜 大和" in out and "伤害 150,000" in out
    assert "Example_Player" in await app.handle(USER, "我")
    assert await app.handle(USER, "解绑") == "已解除绑定。"
    assert await app.handle(USER, "解绑") == "你还没有绑定账号。"
    assert "无法识别用户" in await app.handle(None, "绑定 X")


async def test_recent_idle_and_quota():
    fake, clock, storage, tracker, app = make_env(max_tracked=1)
    assert "还没有足够的近期数据" in await app.handle(USER, "最近 Example_Player")
    clock.t += 2 * 86400
    assert "近 7 天没有新战斗" in await app.handle(USER, "最近 Example_Player")
    tracker.storage.untrack(AID)
    tracker.touch(5, "other")
    assert "追踪名额已满" in await app.handle(USER, "最近 Example_Player")


class BrokenRenderer:
    async def render(self, html):
        raise RuntimeError("no chromium")


class HtmlRenderer:
    def __init__(self):
        self.html = []

    async def render(self, html):
        self.html.append(html)
        return b"PNG"


async def test_render_fallback_and_escaping():
    fake, clock, storage, tracker, app = make_env(renderer=BrokenRenderer())
    assert "【总战绩" in await app.handle(USER, "Example_Player")
    fake, clock, storage, tracker, app = make_env(renderer=HtmlRenderer())
    fake.account["nickname"] = "<script>alert(1)</script>"
    fake.clan = "<i>Z"
    assert await app.handle(USER, "Example_Player") == b"PNG"
    html = app.renderer.html[-1]
    assert "<script>alert" not in html and "&lt;script&gt;" in html and "<i>Z" not in html and "&lt;i&gt;Z" in html


async def test_internal_error_is_generic():
    fake, clock, storage, tracker, app = make_env()
    fake.account["statistics"] = "broken"
    out = await app.handle(USER, "Example_Player")
    assert isinstance(out, str) and "test-application-id" not in out


def test_state_cards_html():
    who = views.Identity(AID, "P", "")
    for st in (views.state_hidden(who, "总战绩"), views.state_tracking(who, 1792130400, 10),
               views.state_idle(who, 1792130400), views.state_quota(who), views.state_newbie(who, Stat(battles=3, wins=2, losses=1), 50)):
        html = cards.state_html(st, 1792130400)
        assert html.startswith("<!DOCTYPE html>") or "<html" in html


CHROMIUM = os.environ.get("WOWS_TEST_CHROMIUM") or shutil.which("chromium")


@pytest.mark.skipif(not CHROMIUM, reason="no Chromium available")
async def test_real_chromium_render():
    renderer = CardRenderer(CHROMIUM, 1)
    fake, clock, storage, tracker, app = make_env(renderer=renderer)
    try:
        png = await app.handle(USER, "Example_Player")
        assert isinstance(png, bytes) and png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 20000
    finally:
        await renderer.close()


def test_plugin_loaded():
    import nonebot
    plugin = nonebot.get_plugin("nonebot_plugin_wows_asia")
    assert plugin and plugin.metadata.name == "WoWS 亚服战绩"


async def test_tier_distribution_and_no_avatar():
    fake, clock, storage, tracker, app = make_env(renderer=HtmlRenderer())
    from .fakes import SHIPS_INFO
    SHIPS_INFO[2] = {**SHIPS_INFO[2], "tier": 8}
    try:
        assert await app.handle(USER, "Example_Player") == b"PNG"
        html = app.renderer.html[-1]
        assert "等级分布" in html and "repeat(10,1fr)" in html and "avatar" not in html
        text = await WowsApp(app.api, storage, None, tracker=tracker, cache_seconds=0, clock=clock).handle(USER, "Example_Player")
        assert "等级：VIII 300　X 700" in text
    finally:
        SHIPS_INFO[2] = {**SHIPS_INFO[2], "tier": 10}


async def test_unknown_ships_hidden_and_kpi_icons():
    fake, clock, storage, tracker, app = make_env(renderer=HtmlRenderer())
    from .fakes import stat
    fake.ships.append({"ship_id": 999, "pvp": stat(33, 23, 10, 600000, 10, 33000, 9)})
    assert await app.handle(USER, "Example_Player") == b"PNG"
    html = app.renderer.html[-1]
    assert ">其他<" not in html and html.count('class="kico"') == 6 and html.count('class="sico"') == 4


def test_state_icon_not_absolute():
    who = views.Identity(AID, "P", "")
    html = cards.state_html(views.state_tracking(who, 1792130400, 10), 1792130400)
    assert 'class="ico"' in html and ".ico{position:absolute" not in html
