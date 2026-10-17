import copy

import httpx

from nonebot_plugin_wows_asia.api import WowsApi

AID = 2000000001
SHIPS_INFO = {
    1: {"ship_id": 1, "name": "大和", "tier": 10, "type": "Battleship"},
    2: {"ship_id": 2, "name": "得梅因", "tier": 10, "type": "Cruiser"},
    3: {"ship_id": 3, "name": "岛风", "tier": 10, "type": "Destroyer"},
    4: {"ship_id": 4, "name": "哈兰德", "tier": 10, "type": "Destroyer"},
}


def stat(b, w, l, dmg, fr, xp, sv, hits=0, shots=0):
    return {"battles": b, "wins": w, "losses": l, "damage_dealt": dmg, "frags": fr, "xp": xp,
            "survived_battles": sv, "main_battery": {"hits": hits, "shots": shots}}


def account(nickname="Example_Player", battles=1000, hidden=False, lbt=1792123200):
    if hidden:
        return {"account_id": AID, "nickname": nickname, "hidden_profile": True, "last_battle_time": lbt}
    pvp = stat(battles, battles * 55 // 100, battles * 44 // 100, battles * 63000, battles * 85 // 100,
               battles * 1500, battles * 48 // 100, 31000, 100000)
    pvp.update(max_damage_dealt=287640, max_damage_dealt_ship_id=1, max_frags_battle=7, max_frags_ship_id=2,
               max_xp=4812, max_xp_ship_id=1, max_damage_scouting=195300, max_scouting_damage_ship_id=3)
    return {"account_id": AID, "nickname": nickname, "hidden_profile": False, "created_at": 1552000000,
            "last_battle_time": lbt, "stats_updated_at": lbt,
            "statistics": {"pvp": pvp, "rank_solo": stat(100, 51, 49, 5800000, 80, 140000, 44),
                           "pvp_solo": {"battles": 700, "wins": 370}, "pvp_div2": {"battles": 200, "wins": 113},
                           "pvp_div3": {"battles": 100, "wins": 59}}}


def ships():
    return [
        {"ship_id": 1, "pvp": stat(400, 230, 168, 38600000, 380, 620000, 200, 9000, 30000),
         "rank_solo": stat(40, 21, 19, 3800000, 30, 60000, 20),
         "pvp_solo": {"battles": 300}, "pvp_div2": {"battles": 100}, "pvp_div3": {"battles": 0}},
        {"ship_id": 2, "pvp": stat(300, 160, 138, 22400000, 260, 450000, 140, 15000, 45000), "rank_solo": None,
         "pvp_solo": {"battles": 300}, "pvp_div2": None, "pvp_div3": None},
        {"ship_id": 3, "pvp": stat(200, 100, 99, 11780000, 150, 280000, 80),
         "pvp_solo": {"battles": 150}, "pvp_div3": {"battles": 50}},
        {"ship_id": 4, "pvp": stat(100, 52, 48, 5520000, 60, 140000, 60)},
    ]


class FakeWG:
    def __init__(self):
        self.account = account()
        self.ships = ships()
        self.calls = []
        self.search = [{"account_id": AID, "nickname": "Example_Player"}]
        self.reject_extra = False
        self.clan = "NYAN"
        self.ladder = {"league": 4, "division": 3, "battles_count": 12, "season_number": 35, "color": "#b3b3b3"}
        self.clan_color = "#cc9966"
        self.ladder_status = 200

    def handler(self, request: httpx.Request):
        if request.url.host == "clans.worldofwarships.asia":
            self.calls.append((request.url.path, dict(request.url.params)))
            if "application_id" in request.url.params:
                return httpx.Response(400)
            if self.ladder_status != 200:
                return httpx.Response(self.ladder_status)
            return httpx.Response(200, json={"clanview": {"clan": {"tag": self.clan, "color": self.clan_color},
                                                           "wows_ladder": self.ladder}})
        path = request.url.path.split("/wows/", 1)[1]
        params = dict(request.url.params)
        self.calls.append((path, params))
        if self.reject_extra and "extra" in params and path in ("account/info/", "ships/stats/"):
            return httpx.Response(200, json={"status": "error", "error": {"message": "INVALID_EXTRA"}})
        if path == "account/list/":
            return ok(self.search)
        if path == "account/info/":
            data = {}
            for aid in params["account_id"].split(","):
                data[aid] = copy.deepcopy(self.account) if int(aid) == AID else None
            return ok(data)
        if path == "ships/stats/":
            if self.account.get("hidden_profile"):
                return ok({str(AID): None})
            return ok({str(AID): copy.deepcopy(self.ships)})
        if path == "encyclopedia/ships/":
            return ok({i: SHIPS_INFO.get(int(i)) for i in params["ship_id"].split(",")})
        if path == "clans/accountinfo/":
            return ok({str(AID): {"clan_id": 2000021407, "clan": {"tag": self.clan, "name": "楊椿雪樂"}}
                       if self.clan else None})
        return httpx.Response(404)

    def play(self, ship_id, mode="pvp", b=1, w=1, l=0, dmg=100000, fr=2, xp=2000, sv=1, hits=0, shots=0,
             team="pvp_solo"):
        for s in self.ships:
            if s["ship_id"] == ship_id:
                cur = s.get(mode) or stat(0, 0, 0, 0, 0, 0, 0)
                for k, v in (("battles", b), ("wins", w), ("losses", l), ("damage_dealt", dmg), ("frags", fr),
                             ("xp", xp), ("survived_battles", sv)):
                    cur[k] += v
                cur["main_battery"]["hits"] += hits
                cur["main_battery"]["shots"] += shots
                s[mode] = cur
                if mode == "pvp" and team:
                    block = s.get(team) or {"battles": 0}
                    block["battles"] += b
                    s[team] = block
        self.account["last_battle_time"] += 600


def ok(data):
    return httpx.Response(200, json={"status": "ok", "data": data})


def make_api(fake: FakeWG) -> WowsApi:
    return WowsApi("test-application-id", transport=httpx.MockTransport(fake.handler), min_interval=0)


class Clock:
    def __init__(self, t=1792130400):  # 2026-10-16 ~14:00 UTC+8
        self.t = t

    def __call__(self):
        return self.t
