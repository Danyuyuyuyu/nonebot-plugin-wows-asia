"""Forgiving ship-name lookup for 船=xxx: typos and homophones (大合 -> 大和) among the ships a player has played."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache

try:
    from pypinyin import Style, pinyin
except ImportError:  # pragma: no cover - optional at runtime: matching falls back to characters only
    pinyin = None

AUTO_SCORE = 0.66  # one clear candidate at least this close is used directly (and the correction shown)
SUGGEST_SCORE = 0.5  # weaker candidates are only offered as "是不是想查"
_FUZZY = [(re.compile(r"^([zcs])h"), r"\1"), (re.compile(r"^n"), "l"), (re.compile(r"^r"), "l"),
          (re.compile(r"(in|en|an)g$"), r"\1")]


@dataclass
class ShipMatch:
    ids: set[int] = field(default_factory=set)  # ships to use; empty = no confident match
    corrected: bool = False  # ids came from typo / homophone matching, not a plain substring hit
    suggestions: list[str] = field(default_factory=list)  # close-but-unsure names when ids is empty


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    return "".join(c for c in text if c.isalnum())


def _fuzzy(syllable: str) -> str:
    for pattern, repl in _FUZZY:
        syllable = pattern.sub(repl, syllable)
    return syllable


@lru_cache(maxsize=4096)
def _readings(char: str, loose: bool) -> frozenset[str]:
    """Every pinyin reading of a CJK char (polyphones included, 長 -> chang/zhang); loose also merges
    commonly confused sounds (zh/z, n/l, ing/in...)."""
    if pinyin is None or not ("\u3400" <= char <= "\u9fff" or "\uf900" <= char <= "\ufaff"):
        return frozenset((char,))
    readings = pinyin(char, style=Style.NORMAL, heteronym=True)[0]
    return frozenset(_fuzzy(p) if loose else p for p in readings) or frozenset((char,))


def _units(text: str, loose: bool = True) -> list[frozenset[str]]:
    return [_readings(c, loose) for c in text]


def _overlap(a: frozenset[str], b: frozenset[str]) -> bool:
    return bool(a & b)


def _full(query: list, name: list, same) -> int:
    """Plain edit distance between the whole query and the whole name."""
    prev = list(range(len(name) + 1))
    for i, q in enumerate(query, 1):
        cur = [i]
        for j, n in enumerate(name, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (0 if same(q, n) else 1)))
        prev = cur
    return prev[-1]


def _distance(query: list, name: list, same) -> int:
    """Edit distance from query to the best-matching stretch of name (free start and end inside name)."""
    prev = [0] * (len(name) + 1)
    for q in query:
        cur = [prev[0] + 1]
        for j, n in enumerate(name, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (0 if same(q, n) else 1)))
        prev = cur
    return min(prev)


def _score(query: str, name: str) -> tuple[float, float]:
    """(how well the query fits some stretch of the name, how close it is to the whole name)."""
    q, n, qs, ns = list(query), list(name), _units(query), _units(name)
    part = min(_distance(q, n, str.__eq__), _distance(qs, ns, _overlap))
    whole = min(_full(q, n, str.__eq__), _full(qs, ns, _overlap))
    return 1 - part / len(query), 1 - whole / max(len(query), len(name))


def match_ships(query: str, names: dict[int, str | list[str]]) -> ShipMatch:
    """names: ship_id -> display name, or [display name, other names...] (e.g. client and API names), of the
    candidates - normally the ships in the player's records."""
    key = normalize(query)
    if not key:
        return ShipMatch()
    display = {sid: v if isinstance(v, str) else v[0] for sid, v in names.items()}
    norm = [(sid, normalize(n)) for sid, v in names.items() for n in ([v] if isinstance(v, str) else v)]
    norm = [(sid, n) for sid, n in norm if n]
    hits = {sid for sid, n in norm if key in n}
    if hits:
        return ShipMatch(hits)
    # same pronunciation (大合 -> 大和, 長門 -> 长门): exact readings before loose ones, whole names before parts
    for loose in (False, True):
        units = _units(key, loose)
        whole, part = set(), set()
        for sid, n in norm:
            nu = _units(n, loose)
            if len(nu) == len(units) and _full(units, nu, _overlap) == 0:
                whole.add(sid)
            elif len(nu) > len(units) and _distance(units, nu, _overlap) == 0:
                part.add(sid)
        if whole or part:
            return ShipMatch(whole or part, corrected=True)
    if len(key) < 2:
        return ShipMatch()
    best_of: dict[int, tuple[float, float]] = {}
    for sid, n in norm:
        best_of[sid] = max(best_of.get(sid, (0.0, 0.0)), _score(key, n))
    scored = sorted(((*sc, display[sid], sid) for sid, sc in best_of.items()), reverse=True)
    if not scored or scored[0][0] < SUGGEST_SCORE:
        return ShipMatch()
    best = scored[0][0]
    top = {s[2] for s in scored if s[0] == best}
    runner_up = next((s[0] for s in scored if s[0] < best), 0.0)
    if best >= AUTO_SCORE and len(top) == 1 and best - runner_up >= 0.15:
        return ShipMatch({s[3] for s in scored if s[0] == best}, corrected=True)
    seen: list[str] = []
    for score, _, name, _ in scored:
        if score >= SUGGEST_SCORE and name not in seen:
            seen.append(name)
    return ShipMatch(suggestions=seen[:3])
