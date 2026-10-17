"""Resolve WoWS API ship IDs to the official client names."""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)
DEFAULT_NAME_PATH = Path("data") / "wows_ship" / "names" / "zh_sg.json"


class ShipNameMap:
    """Map API numeric ship IDs to names from the client localization bundle."""

    def __init__(self, path: Path = DEFAULT_NAME_PATH):
        self.path = Path(path)
        self._signature: tuple[int, int] | None = None
        self._names: dict[int, str] = {}
        self._warned_signature: object = object()

    def _file_signature(self) -> tuple[int, int] | None:
        try:
            info = self.path.stat()
        except OSError:
            return None
        return info.st_mtime_ns, info.st_size

    def _reload_if_needed(self) -> None:
        signature = self._file_signature()
        if signature == self._signature:
            return
        if signature is None:
            if self._warned_signature != signature:
                logger.warning("WoWS 客户端船名文件不存在: %s", self.path)
                self._warned_signature = signature
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            names = payload["names"]
            ship_ids = payload["ship_ids"]
            if not isinstance(names, dict) or not isinstance(ship_ids, dict):
                raise ValueError("names/ship_ids must be objects")
            resolved: dict[int, str] = {}
            for raw_id, code in ship_ids.items():
                if not isinstance(raw_id, str) or not raw_id.isdecimal():
                    continue
                if not isinstance(code, str):
                    continue
                name = names.get(code)
                if isinstance(name, str) and name.strip():
                    resolved[int(raw_id)] = name
            if not resolved:
                raise ValueError("the name map is empty")
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            if self._warned_signature != signature:
                logger.warning("WoWS 客户端船名文件无效，继续使用 API 名称: %s (%s)", self.path, exc)
                self._warned_signature = signature
            return
        self._names = resolved
        self._signature = signature
        self._warned_signature = object()

    def name_for(self, ship_id: int, fallback: str) -> str:
        self._reload_if_needed()
        try:
            key = int(ship_id)
        except (TypeError, ValueError):
            return fallback
        return self._names.get(key) or fallback


SHIP_NAMES = ShipNameMap()