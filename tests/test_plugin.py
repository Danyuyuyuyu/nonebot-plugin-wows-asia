import asyncio
import os
import shutil
from dataclasses import replace

import httpx
import pytest

from nonebot_plugin_wows_asia import cards, views
from nonebot_plugin_wows_asia.api import ACCOUNT_FIELDS, ApiRejected, WowsApi
from nonebot_plugin_wows_asia.app import WowsApp
from nonebot_plugin_wows_asia.commands import Command, Query, WowsError, parse_command, parse_query
from nonebot_plugin_wows_asia.renderer import CardRenderer
from nonebot_plugin_wows_asia.stats import Stat, ship_states
from nonebot_plugin_wows_asia.storage import Storage
from nonebot_plugin_wows_asia.tracker import Tracker, diff_states, split_divisions

from .fakes import AID, SHIPS_INFO, Clock, FakeWG, account, make_api, stat

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
    ("生涯", Command("total")),
    ("总战绩 我", Command("total")),
    ("生涯 Foo_Bar", Command("total", Query("name", "Foo_Bar"))),
    ("Foo_Bar 总战绩", Command("total", Query("name", "Foo_Bar"))),
    ("最近 战绩", Command("recent")),
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


async def test_clan_league_colours():
    fake = FakeWG()
    api = make_api(fake)
    info = await api.clan_info(AID)
    assert (info.tag, info.name, info.color, info.league, info.season) == ("NYAN", "楊椿雪樂", "#CC9966", "暴风 III", 35)
    n = len(fake.calls)
    await api.clan_info(AID)
    assert len(fake.calls) == n + 1  # accountinfo again, ladder cached
    api._ladder.clear()
    fake.ladder, fake.clan_color = {"league": 0, "division": 1, "battles_count": 30}, "#cda4ff"
    assert (await api.clan_info(AID)).league == "飓风"
    api._ladder.clear()
    fake.ladder, fake.clan_color = {"league": 4, "division": 2, "battles_count": 0}, "#b3b3b3"
    info = await api.clan_info(AID)
    assert info.league == "未参加军团战" and info.color == "#B3B3B3"
    api._ladder.clear()
    fake.ladder_status = 503
    info = await api.clan_info(AID)
    assert info.tag == "NYAN" and info.league == "" and info.color == "#B3B3B3"
    api._ladder.clear()
    fake.ladder_status, fake.ladder = 200, {"league": 1, "division": 2, "battles_count": 5}
    fake.clan_color = "red;x"
    assert (await api.clan_info(AID)).color == "#B3B3B3"  # malformed colour never reaches CSS


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
    tracker = Tracker(api, storage, clock=clock, max_tracked=app_kw.pop("max_tracked", 200),
                      poll_minutes=app_kw.pop("poll_minutes", 10), fast_minutes=app_kw.pop("fast_minutes", 0))
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
    assert "[NYAN]Example_Player" in text and "1,000 场" in text and "55.00%" in text and "｜暴风 III" in text
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
    assert "【最近战绩" in out and "胜 大和（随机·单野）" in out and "伤害 150,000" in out
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
    fake.clan_color = "#cda4ff"
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



async def test_header_clan_colour_and_no_clan():
    fake, clock, storage, tracker, app = make_env(renderer=HtmlRenderer())
    await app.handle(USER, "Example_Player")
    html = app.renderer.html[-1]
    assert 'class="clan" style="color:#9F774F"' in html and "楊椿雪樂 · 暴风 III" in html
    fake.clan = None
    await app.handle(USER, "Example_Player")
    html = app.renderer.html[-1]
    assert 'class="clan"' not in html and "无军团 · " in html


# ---------------- solo / division split ----------------
def test_split_divisions():
    deltas = [((1, "pvp"), S(battles=1), 1.0), ((1, "pvp_div2"), S(battles=1), None),
              ((2, "pvp"), S(battles=3), 2.0), ((2, "pvp_solo"), S(battles=2), None), ((2, "pvp_div3"), S(battles=1), None),
              ((3, "pvp"), S(battles=1), None), ((3, "pvp_solo"), S(battles=250), None),  # pre-upgrade snapshot
              ((4, "rank_solo"), S(battles=1), None), ((5, "pvp"), S(battles=1), None)]  # extra rejected
    out = {k: div for k, _, _, div in split_divisions(deltas)}
    assert out == {(1, "pvp"): (0, 1, 0), (2, "pvp"): (2, 0, 1), (3, "pvp"): None,
                   (4, "rank_solo"): None, (5, "pvp"): None}
    assert views.team_label((0, 1, 0)) == "双排" and views.team_label((2, 0, 1)) == "单野2 三排1"
    assert views.team_label((3, 0, 0)) == "单野3" and views.team_label(None) == ""


async def test_tracker_records_division_and_card():
    fake, clock, storage, tracker, app = make_env()
    assert "已绑定" in await app.handle(USER, "绑定 Example_Player")
    clock.t += 600
    fake.play(2, team="pvp_div2")
    fake.play(1, team="pvp_div3")
    fake.play(1, team="pvp_solo", w=0, l=1)
    fake.play(3, mode="rank_solo")
    assert await tracker.poll_all() == 3
    by = {(r.ship_id, r.mode): r.division for r in storage.records(AID, 0)}
    assert by == {(2, "pvp"): (0, 1, 0), (1, "pvp"): (1, 0, 1), (3, "rank_solo"): None}
    out = await app.handle(USER, "最近")
    assert "得梅因（随机·双排）" in out and "大和（随机·单野1 三排1）" in out
    recs = storage.records(AID, 0)
    view = views.build_recent(views.Identity("Example_Player", AID), Stat(), recs, {}, clock.t - 900, clock.t)
    assert view.teams == (1, 1, 1)
    html = cards.recent_html(view)
    assert "随机 · 双排" in html and "随机中 单野 1 / 双排 1 / 三排 1" in html


def test_storage_migrates_old_records(tmp_path):
    import sqlite3
    path = tmp_path / "old.sqlite3"
    db = sqlite3.connect(path)
    cols = ", ".join(f"{c} INTEGER NOT NULL" for c in ("battles", "wins", "losses", "damage", "frags", "xp",
                                                        "survived", "hits", "shots"))
    db.execute(f"CREATE TABLE battle_record (id INTEGER PRIMARY KEY AUTOINCREMENT, account_id INTEGER NOT NULL, "
               f"captured_at INTEGER NOT NULL, prev_at INTEGER NOT NULL, ship_id INTEGER NOT NULL, mode TEXT NOT NULL, "
               f"{cols}, career_avg_damage REAL)")
    db.execute("INSERT INTO battle_record VALUES (NULL, 1, 100, 50, 7, 'pvp', 1, 1, 0, 9, 1, 9, 1, 0, 0, NULL)")
    db.commit()
    db.close()
    storage = Storage(path)
    [rec] = storage.records(1, 0)
    assert rec.division is None and rec.stat.damage == 9
    storage.close()


async def test_fast_lane_polling():
    fake, clock, storage, tracker, app = make_env(poll_minutes=10, fast_minutes=3)
    assert tracker.tick_minutes == 3 and "3 分钟" in tracker.interval_text()
    tracker.touch(AID, "Example_Player")
    tracker.touch(42, "Ghost")  # no baseline yet -> stays in the fast lane
    await tracker.poll_all()  # first tick is a full tick and creates AID's baseline

    def polled_ids():
        n = len(fake.calls)

        async def run():
            await tracker.poll_all()
            ids = [p["account_id"] for path, p in fake.calls[n:] if path == "account/info/"]
            return set(ids[0].split(",")) if ids else set()
        return run()

    storage.mark_polled(AID, clock.t, 1, False)  # AID: unbound, last battle long ago -> slow lane only
    clock.t += 180
    assert await polled_ids() == {"42"}
    storage.bind(USER, AID, "Example_Player", clock.t)  # bound -> fast lane
    clock.t += 180
    assert await polled_ids() == {"42", str(AID)}
    storage.unbind(USER)
    clock.t += 180  # 9 min (+ half a tick) since the last full tick -> full tick, everyone polled
    assert await polled_ids() == {"42", str(AID)}
    clock.t += 180
    assert await polled_ids() == {"42"}
    storage.mark_polled(AID, clock.t, clock.t - 600, False)  # played recently -> fast lane
    clock.t += 180
    assert await polled_ids() == {"42", str(AID)}
    assert Tracker(tracker.api, storage, poll_minutes=5, fast_minutes=5).tick_minutes == 5  # fast >= poll: off


# ---------------- 场次 / 单场 (0.2.7) ----------------
from nonebot_plugin_wows_asia.commands import Filter  # noqa: E402
from nonebot_plugin_wows_asia.storage import BEST_DAMAGE, Record  # noqa: E402


@pytest.mark.parametrize(("raw", "action", "target", "flt"), [
    ("单场 今天 按伤害", "battle", None, Filter(period=("ago", 0, 0), sort="damage")),
    ("场次 我 昨天 船=大和", "battles", None, Filter(period=("ago", 1, 1), ship="大和")),
    ("场次 张三 排位 近3天 前5", "battles", Query("name", "张三"), Filter(period=("ago", 2, 0), mode="rank_solo", limit=5)),
    ("单场 3", "battle", None, Filter(index=3)),
    ("单场 第2把 伤害最高", "battle", None, Filter(index=2, sort="damage")),
    ("场次 id 7 组队 胜", "battles", Query("id", "7"), Filter(mode="pvp", team="div", result="win")),
    ("场次 10-12~10-15 双排 按经验", "battles", None, Filter(period=("date", (10, 12), (10, 15)), mode="pvp", team="div2", sort="xp")),
    ("场次 船：得梅因 10月15日", "battles", None, Filter(period=("date", (10, 15), (10, 15)), ship="得梅因")),
    ("单场 今天 伤害最低", "battle", None, Filter(period=("ago", 0, 0), sort="damage", asc=True)),
    ("场次 最少击沉 前3", "battles", None, Filter(sort="frags", asc=True, limit=3)),
    ("场次 近3天 最差5把", "battles", None, Filter(period=("ago", 2, 0), sort="xp", asc=True, limit=5)),
    ("场次 打得最好的", "battles", None, Filter(sort="xp")),
    ("场次 最好 按经验", "battles", None, Filter(sort="xp")),
    ("单场 最差 第2把", "battle", None, Filter(sort="xp", asc=True, index=2)),
    ("场次 divinesk 今天下午 船=伊吹", "battles", Query("name", "divinesk"),
     Filter(period=("ago", 0, 0), hours=(12, 18), ship="伊吹")),
    ("场次 下午", "battles", None, Filter(period=("ago", 0, 0), hours=(12, 18))),
    ("场次 昨天 晚上", "battles", None, Filter(period=("ago", 1, 1), hours=(18, 24))),
    ("场次 近3天 14点后", "battles", None, Filter(period=("ago", 2, 0), hours=(14, 24))),
    ("场次 9点前", "battles", None, Filter(period=("ago", 0, 0), hours=(0, 9))),
    ("场次 14-18点", "battles", None, Filter(period=("ago", 0, 0), hours=(14, 18))),
])
def test_parse_battle_filters(raw, action, target, flt):
    assert parse_command(raw) == Command(action, target, flt)


@pytest.mark.parametrize("raw", ["场次 a b", "场次 今天 昨天", "场次 排位 单野", "场次 13-40", "单场 0", "场次 近200天",
                                 "场次 伤害最高 伤害最低", "场次 按伤害 最差", "场次 最好 最差",
                                 "场次 下午 晚上", "场次 昨天 今天下午", "场次 18-14点", "场次 25点后"])
def test_parse_battle_filter_errors(raw):
    with pytest.raises(WowsError):
        parse_command(raw)


def _rec(ts, ship=1, mode="pvp", dmg=100000, w=1, div=(1, 0, 0), n=1, full=True):
    return Record(AID, ts, ts - 600, ship, mode, S(battles=n, wins=w, losses=n - w, damage=dmg, survived=1), 90000.0,
                  div if mode == "pvp" else None, full)


def test_filter_records():
    from nonebot_plugin_wows_asia.api import ShipInfo
    now = 1792130400  # 2026-10-16 14:00 CST
    infos = {1: ShipInfo(1, "大和", 10, "Battleship"), 2: ShipInfo(2, "得梅因", 10, "Cruiser")}
    recs = [_rec(now - 600, 1, dmg=150000), _rec(now - 3600, 2, dmg=200000, div=(0, 1, 0)),
            _rec(now - 86400, 1, dmg=90000, w=0), _rec(now - 86400 - 1800, 1, mode="rank_solo", dmg=50000),
            _rec(now - 86400 - 3600, 1, dmg=300000, n=2, div=(1, 1, 0), w=1, full=False)]
    pick = lambda **kw: views.filter_records(recs, Filter(**kw), infos, now, default_days=None)  # noqa: E731
    assert [r.stat.damage for r in pick(period=("ago", 0, 0), sort="damage").records] == [200000, 150000]
    p = pick(period=("ago", 1, 1), ship="大")
    assert len(p.records) == 3 and p.desc == "昨天 · 大和"
    assert [r.mode for r in pick(mode="rank_solo").records] == ["rank_solo"]
    assert [r.ship_id for r in pick(team="div2").records] == [2]
    assert len(pick(team="solo").records) == 2  # the mixed merged row is neither solo nor div
    assert all(r.stat.losses == 0 for r in pick(result="win").records)
    assert pick(sort="damage").records[0].stat.damage == 200000  # merged row ranks by its per-battle average
    assert pick(ship="岛风").empty_reason == "记录里没有名字含“岛风”的船。最近打过：大和 / 得梅因"
    assert pick(sort="scouting").records and not any(not r.full for r in pick(sort="scouting").records)
    low = pick(sort="damage", asc=True)
    assert [r.stat.damage for r in low.records][:2] == [50000, 90000] and low.desc.endswith("按伤害从低到高")
    # equal values (all 0 kills here) fall back to damage in the same direction
    assert [r.stat.damage for r in pick(period=("ago", 0, 0), sort="frags", asc=True).records] == [150000, 200000]
    assert [r.stat.damage for r in pick(period=("ago", 0, 0), sort="frags").records] == [200000, 150000]
    # time of day (records at 13:50 and 13:00 today; 14:00 / 13:30 / 13:00 yesterday, UTC+8)
    late = pick(period=("ago", 0, 0), hours=(13, 14))
    assert [r.stat.damage for r in late.records] == [150000, 200000] and late.desc == "今天 · 13–14点"
    assert not pick(period=("ago", 0, 0), hours=(14, 24)).records
    noon = pick(period=("ago", 1, 1), hours=(12, 18))
    assert len(noon.records) == 3 and noon.desc.startswith("昨天下午")
    # typo / homophone correction among the player's ships
    assert pick(ship="大合").desc == "全部记录 · 大和（由“大合”纠正）" and len(pick(ship="大合").records) == 4
    assert pick(ship="得每因").records[0].ship_id == 2
    # explicit dates resolve to the most recent past occurrence
    assert len(pick(period=("date", (10, 15), (10, 16))).records) == 5
    assert views.filter_records(recs, Filter(), infos, now, default_days=7).desc == "近 7 天"


async def test_tracker_records_details_bests_and_upgrade():
    fake, clock, storage, tracker, _ = make_env()
    tracker.touch(AID, "Example_Player")
    await tracker.refresh(AID, last_battle_time=fake.account["last_battle_time"])
    clock.t += 600
    fake.play(1, dmg=400000, scouting=45000, potential=2000000, spotted=4, planes=7, torp=(0, 0))
    assert await tracker.poll_all() == 1
    [rec] = storage.records(AID, 0)
    assert rec.full and rec.stat.scouting == 45000 and rec.stat.potential == 2000000 and rec.stat.spotted == 4
    assert rec.best & BEST_DAMAGE  # 400k beats the stored max_damage_dealt
    # a pre-0.2.7 snapshot (full=0) is rewritten on the next tick even without a new battle
    storage._run("UPDATE ship_state SET full=0 WHERE account_id=?", (AID,))
    assert storage.stale_accounts() == {AID}
    clock.t += 600
    n = len(fake.calls)
    assert await tracker.poll_all() == 0
    assert "ships/stats/" in [p for p, _ in fake.calls[n:]] and storage.stale_accounts() == set()


async def test_battles_and_battle_commands():
    fake, clock, storage, tracker, app = make_env()
    await app.handle(USER, "绑定 Example_Player")
    clock.t += 600
    fake.play(1, dmg=150000, team="pvp_div2")
    await tracker.poll_all()
    clock.t += 600
    fake.play(2, dmg=90000, w=0, l=1, sv=0)
    await tracker.poll_all()
    out = await app.handle(USER, "场次 今天")
    assert "【场次 · 今天】" in out and "2 场 1胜1负" in out and "大和（随机·双排）" in out
    out = await app.handle(USER, "单场 今天 按伤害")
    assert "第 1 / 共 2 场" in out and "伤害 150,000" in out and "侦察伤害" in out
    assert "倒数第 2 场 · 按时间第 1 / 共 2 场" in await app.handle(USER, "单场 2")
    assert "只有 2 场符合条件" in await app.handle(USER, "单场 5")
    assert "没有名字含“岛风”" in await app.handle(USER, "场次 船=岛风")
    out = await app.handle(USER, "单场 今天")
    assert "最新一场 · 按时间第 2 / 共 2 场" in out and "共 2 场，只显示了 1 场" in out
    assert "大和（由“大合”纠正）" in await app.handle(USER, "场次 船=大合")
    assert "共 2 场" not in await app.handle(USER, "单场 船=得梅因")
    # @mention reads the mentioned user's binding
    assert "对方还没有绑定" in await app.handle("OneBot V11:2", "场次", mentions=["OneBot V11:3"])
    assert "【场次" in await app.handle("OneBot V11:2", "场次 今天", mentions=[USER])


async def test_ai_invocation_gets_caption():
    class R:
        async def render(self, html):
            return b"PNG"

    fake, clock, storage, tracker, app = make_env(renderer=R())
    await app.handle(USER, "绑定 Example_Player")
    assert await app.handle(USER, "Example_Player") == b"PNG"
    image, caption = await app.handle(USER, "Example_Player", ai=True)
    assert image == b"PNG" and caption.startswith("Example_Player 总战绩：随机 1,000 场")
    clock.t += 600
    fake.play(1, dmg=150000)
    await tracker.poll_all()
    _, caption = await app.handle(USER, "单场", ai=True)
    assert caption.startswith("Example_Player【单场") and "伤害 150,000" in caption


def test_storage_migrates_old_ship_state(tmp_path):
    import sqlite3
    path = tmp_path / "v026.sqlite3"
    db = sqlite3.connect(path)
    cols = ", ".join(f"{c} INTEGER NOT NULL" for c in ("battles", "wins", "losses", "damage", "frags", "xp",
                                                        "survived", "hits", "shots"))
    db.execute(f"CREATE TABLE ship_state (account_id INTEGER NOT NULL, ship_id INTEGER NOT NULL, mode TEXT NOT NULL, "
               f"{cols}, PRIMARY KEY (account_id, ship_id, mode))")
    db.execute("INSERT INTO ship_state VALUES (1, 7, 'pvp', 10, 5, 5, 900, 9, 90, 4, 0, 0)")
    db.commit()
    db.close()
    storage = Storage(path)
    assert storage.ship_states(1)[(7, "pvp")].damage == 900
    assert storage.ship_meta(1) == {(7, "pvp"): (False, None)} and storage.stale_accounts() == {1}
    storage.close()


async def test_refresh_serialised_per_account():
    fake, clock, storage, tracker, _ = make_env()
    tracker.touch(AID, "Example_Player")
    await tracker.refresh(AID, last_battle_time=fake.account["last_battle_time"])
    clock.t += 600
    fake.play(1, dmg=120000)
    real, gate, calls = tracker.api.ship_stats, asyncio.Event(), []

    async def slow(account_id):
        calls.append(account_id)
        await gate.wait()
        return await real(account_id)

    tracker.api.ship_stats = slow
    lbt = fake.account["last_battle_time"]
    poll = asyncio.create_task(tracker.refresh(AID, last_battle_time=lbt, force=True))
    await asyncio.sleep(0)
    user = asyncio.create_task(tracker.refresh(AID, last_battle_time=lbt))
    await asyncio.sleep(0)
    assert calls == [AID]  # the user query waits instead of diffing the same snapshot
    gate.set()
    first, second = await asyncio.gather(poll, user)
    assert first.new_records == 1 and second.skipped and calls == [AID]
    assert len(storage.records(AID, 0)) == 1 and not tracker._locks


async def test_stale_response_never_rolls_snapshot_back():
    fake, clock, storage, tracker, _ = make_env()
    tracker.touch(AID, "Example_Player")
    await tracker.refresh(AID, last_battle_time=fake.account["last_battle_time"])
    stale = await tracker.api.ship_stats(AID)
    clock.t += 600
    fake.play(1, dmg=120000)
    assert (await tracker.refresh(AID, last_battle_time=fake.account["last_battle_time"])).new_records == 1
    battles = storage.ship_states(AID)[(1, "pvp")].battles
    real = tracker.api.ship_stats

    async def cached(account_id):
        return stale

    tracker.api.ship_stats = cached
    clock.t += 600
    assert (await tracker.refresh(AID, force=True)).new_records == 0
    assert storage.ship_states(AID)[(1, "pvp")].battles == battles  # stale data ignored
    tracker.api.ship_stats = real
    clock.t += 600
    assert (await tracker.refresh(AID, force=True)).new_records == 0
    assert len(storage.records(AID, 0)) == 1


def test_same_battle_window_stored_once():
    storage = Storage(":memory:")
    rec = Record(AID, 100, 50, 1, "pvp", Stat(battles=1, wins=1, damage=90000), 80000.0, end_battles=101)
    assert storage.save_snapshot(AID, {}, [rec]) == 1
    assert storage.save_snapshot(AID, {}, [replace(rec, captured_at=200)]) == 0
    legacy = replace(rec, end_battles=None)  # rows from before 0.2.8 carry no window key
    assert storage.save_snapshot(AID, {}, [legacy, legacy]) == 2
    assert [r.end_battles for r in storage.records(AID, 0)] == [None, None, 101]


def test_ship_match():
    from nonebot_plugin_wows_asia.ship_match import match_ships
    names = {1: "大和", 2: "得梅因", 3: "伊吹", 4: "伊势", 5: "圣路易斯", 6: "路易斯安那", 7: "长门", 8: "吹雪",
             9: ["蒙大拿", "Montana"]}

    def m(q):
        r = match_ships(q, names)
        return sorted(r.ids), r.corrected, r.suggestions

    assert m("大和") == ([1], False, [])
    assert m("吹") == ([3, 8], False, [])  # plain substring keeps every hit
    assert m("大合") == ([1], True, [])  # homophone
    assert m("衣吹") == ([3], True, [])
    assert m("依势") == ([4], True, [])  # exact readings win over loose ones (势 shi vs 斯 si)
    assert m("長門") == ([7], True, [])  # traditional characters / polyphones
    assert m("的梅因") == ([2], True, [])
    assert m("路易斯按那") == ([6], True, [])  # typo
    assert m("montna") == ([9], True, [])  # other names (API / English) count too
    assert m("伊次")[0] == [] and m("伊次")[2][0] == "伊吹"  # unsure: only suggestions
    assert m("xyz") == ([], False, [])


def test_ai_guide_examples_parse():
    import re

    from nonebot_plugin_wows_asia import AI_GUIDE
    assert len(AI_GUIDE) <= 900  # sent with every LLM request: keep it short
    line = next(x for x in AI_GUIDE.splitlines() if x.strip().startswith("例："))
    examples = re.findall(r"→(wows [^；。]+)", line)
    assert len(examples) >= 6
    actions = {"最近": "recent", "场次": "battles", "单场": "battle", "绑定": "bind", "单船": "ship", "战舰": "ship"}
    for example in examples:
        args = example.split()[1:]
        cmd = parse_command(" ".join(args))
        assert cmd.action == actions.get(args[0], "total"), example


def test_no_data_cards_carry_career_summary():
    who = views.Identity(AID, "Example_Player")
    career = Stat(battles=1000, wins=550, losses=450, damage=80_000_000)
    for st in (views.state_tracking(who, 1792130400, "每 3 分钟检查一次", career), views.state_idle(who, 1792130400, career)):
        assert "生涯随机 1,000 场 · 胜率 55.0% · 场均伤害 80,000" in st.tip and "/wows" not in st.tip
    assert views.state_tracking(who, 1792130400, "x").tip.startswith("打几场")


def test_parse_ship_command():
    cmd = parse_command("单船 大和")
    assert cmd.action == "ship" and cmd.target is None and cmd.filter.ship == "大和" and cmd.filter.mode is None
    cmd = parse_command("战舰 伊吹 张三")
    assert cmd.action == "ship" and cmd.target == Query("name", "张三") and cmd.filter.ship == "伊吹"
    assert parse_command("单船 我 大和").filter.ship == "大和"
    assert parse_command("单船 大和 id 2000000001").target == Query("id", "2000000001")
    cmd = parse_command("单船 大和 排位")
    assert cmd.filter.mode == "rank_solo" and cmd.target is None
    cmd = parse_command("张三 船=大和")  # total + ship -> that ship's career
    assert cmd.action == "ship" and cmd.target == Query("name", "张三") and cmd.filter.ship == "大和"
    assert parse_command("单船 张三 船=大和").target == Query("name", "张三")
    assert parse_command("船=大和").action == "ship"
    for bad in ("单船", "单船 大和 张三 李四", "单船 船=大和 船=伊吹"):
        with pytest.raises(WowsError):
            parse_command(bad)
    assert parse_command("张三").action == "total"


async def test_ship_card_career_peers_and_divisions():
    fake, clock, storage, tracker, app = make_env()
    card = await app.ship_card(AID, parse_command("单船 岛风").filter)
    assert "【单船 · 岛风（X 级驱逐舰） · 随机】" in card.text
    assert "200 场｜胜率 50.00%｜场均伤害 58,900" in card.text
    assert "同级驱逐舰（1 艘）：胜率 52.0%｜场均伤害 55,200" in card.text  # 哈兰德
    assert "单场最高：伤害 176,700｜击沉 5" in card.text
    assert "常用第 3 / 共 4 艘" in card.html and "低于整体 −6.5%" in card.html
    big = await app.ship_card(AID, parse_command("单船 大和").filter)
    assert "随机组队：单野 300 场 56.0%　双排 100 场 62.0%" in big.text
    assert "本船排位：40 场｜胜率 52.5%" in big.text
    assert "TA 第 1 常用的船" in big.caption and "同级" not in big.caption  # no other X battleship
    ranked = await app.ship_card(AID, parse_command("单船 大和 排位").filter)
    assert "· 排位】" in ranked.text and "本船随机：400 场" in ranked.text and "随机组队：单野 300 场" in ranked.text


async def test_ship_card_typo_ambiguous_and_missing():
    fake, clock, storage, tracker, app = make_env()
    card = await app.ship_card(AID, parse_command("单船 大合").filter)
    assert "大和（X 级战列舰，由“大合”纠正）" in card.text and "已把“大合”纠正为“大和”" in card.html
    fake.ships.append({"ship_id": 5, "pvp": stat(10, 5, 5, 500000, 5, 10000, 5)})
    SHIPS_INFO[5] = {"ship_id": 5, "name": "岛风改", "tier": 10, "type": "Destroyer"}
    try:
        app.api._ships.clear()
        card = await app.ship_card(AID, parse_command("单船 岛风").filter)
        assert "【单船 · 岛风（X 级驱逐舰）" in card.text and "同时匹配：岛风改" in card.text
        card = await app.ship_card(AID, parse_command("单船 风").filter)  # no exact name: the most played
        assert "【单船 · 岛风（" in card.text
    finally:
        SHIPS_INFO.pop(5)
    missing = await app.ship_card(AID, parse_command("单船 蒙大拿").filter)
    assert "没开过“蒙大拿”" in missing.text and "TA 开得最多的：大和 / 得梅因 / 岛风" in missing.text


async def test_ship_card_history_and_hidden():
    fake, clock, storage, tracker, app = make_env()
    await app.handle("u1", "绑定 Example_Player")
    for dmg in (90000, 150000):
        fake.play(3, dmg=dmg)
        clock.t += 700
        await tracker.refresh(AID, last_battle_time=fake.account["last_battle_time"])
    card = await app.ship_card(AID, parse_command("单船 岛风").filter)
    assert "记录到的最近 2 场" in card.html and "150k" in card.html
    reply = await app.handle("u1", "单船 岛风")
    assert isinstance(reply, str) and "【单船 · 岛风" in reply  # renderer=None -> text
    fake.account = account(hidden=True)
    app._cache.clear()
    assert "隐藏了战绩" in (await app.handle("u1", "单船 岛风"))


async def test_short_nickname_is_rejected_before_search():
    fake, clock, storage, tracker, app = make_env()
    reply = await app.handle("u1", "Pi")
    assert "昵称至少 3 个字符" in reply and "NOT_ENOUGH" not in reply
    assert not any(path == "account/list/" for path, _ in fake.calls)
    assert parse_command("单船 大和 生涯").target is None
