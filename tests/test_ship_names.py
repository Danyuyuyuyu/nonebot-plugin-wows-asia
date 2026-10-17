import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

PACKAGE = "nonebot_plugin_wows_asia"
PACKAGE_PATH = Path(__file__).resolve().parents[1] / PACKAGE
if PACKAGE not in sys.modules:
    package = types.ModuleType(PACKAGE)
    package.__path__ = [str(PACKAGE_PATH)]
    sys.modules[PACKAGE] = package

from nonebot_plugin_wows_asia import views
from nonebot_plugin_wows_asia.api import ShipInfo
from nonebot_plugin_wows_asia.commands import WowsError, parse_command
from nonebot_plugin_wows_asia.ship_names import ShipNameMap
from nonebot_plugin_wows_asia.stats import Stat
from nonebot_plugin_wows_asia.storage import Record


def write_names(path, name="Official Yamato"):
    path.write_text(
        json.dumps({"names": {"PJSB018": name}, "ship_ids": {"123": "PJSB018"}}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_ship_id_uses_client_name(tmp_path):
    path = tmp_path / "zh_sg.json"
    write_names(path)
    resolver = ShipNameMap(path)
    assert resolver.name_for(123, "API name") == "Official Yamato"
    assert resolver.name_for(999, "API name") == "API name"


def test_ship_label_uses_client_name_and_handles_unknown_info(tmp_path, monkeypatch):
    path = tmp_path / "zh_sg.json"
    write_names(path)
    monkeypatch.setattr(views, "SHIP_NAMES", ShipNameMap(path))
    assert views.ship_label(ShipInfo(123, "API name", 10, "Battleship"), 123)[0] == "Official Yamato"
    assert views.ship_label(None, 123)[0] == "Official Yamato"


def test_invalid_name_file_falls_back(tmp_path):
    path = tmp_path / "zh_sg.json"
    path.write_text("{", encoding="utf-8")
    assert ShipNameMap(path).name_for(123, "API name") == "API name"


def test_ship_filter_uses_client_name(tmp_path, monkeypatch):
    path = tmp_path / "zh_sg.json"
    write_names(path)
    monkeypatch.setattr(views, "SHIP_NAMES", ShipNameMap(path))
    record = Record(1, 1700000000, 1699999900, 123, "pvp", Stat(battles=1, wins=1), None)
    flt = SimpleNamespace(
        period=None, ship="Official Yamato", mode=None, team=None,
        result=None, sort=None, limit=None, index=None,
    )
    picked = views.filter_records([record], flt, {123: ShipInfo(123, "API name", 10, "Battleship")},
                                  1700000000, default_days=None)
    assert picked.records == [record]


def test_invalid_calendar_date_is_rejected():
    with pytest.raises(WowsError, match="日期"):
        parse_command("场次 2月30日")