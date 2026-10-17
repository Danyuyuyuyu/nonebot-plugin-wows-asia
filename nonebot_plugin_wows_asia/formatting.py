"""Plain-text fallbacks (used when image rendering is disabled or fails)."""
from .cards import n0, pct
from .views import RecentView, StateView, TotalView, roman


def candidates_text(candidates: list[dict]) -> str:
    if not candidates:
        return "亚服未找到该昵称，请检查完整拼写和服务器；也可使用 /wows id 账号ID。"
    from .views import clean
    rows = ["未定位到唯一账号，以下是匹配或前缀候选（最多 5 条）："]
    rows += [f"{clean(r['nickname'])} | /wows id {r['account_id']}" for r in candidates]
    return "\n".join(rows)


def _title(who) -> str:
    clan = f"[{who.clan}]" if who.clan else ""
    league = f"｜{who.clan_league}" if who.clan and who.clan_league else ""
    return f"WoWS 亚服｜{clan}{who.nickname}\n账号 ID：{who.account_id}{league}"


def total_text(v: TotalView) -> str:
    s = v.random
    lines = [_title(v.who), "【总战绩 · 随机】",
             f"战斗：{s.battles:,} 场｜胜率：{pct(s.win_rate, 2)}",
             f"场均伤害：{n0(s.per('damage'))}｜场均击沉：{'—' if s.per('frags') is None else format(s.per('frags'), '.2f')}",
             f"存活率：{pct(s.survival, 2)}｜主炮命中率：{pct(s.hit_rate, 2)}"]
    if v.types:
        lines.append("舰种：" + "　".join(f"{t.name} {t.battles} 场 {t.wins / t.battles * 100:.1f}%" for t in v.types))
    if v.tiers:
        lines.append("等级：" + "　".join(f"{roman(t.tier)} {t.battles}" for t in v.tiers if t.battles))
    if v.ranked:
        lines.append(f"排位：{v.ranked.battles:,} 场｜胜率 {pct(v.ranked.win_rate)}")
    for label, value, ship in v.records:
        lines.append(f"{label}：{value:,}" + (f"（{ship}）" if ship else ""))
    return "\n".join(lines)


def recent_text(v: RecentView) -> str:
    s = v.summary
    lines = [_title(v.who), f"【最近战绩 {v.start} 至 {v.end}】",
             f"{s.battles} 场｜胜率 {pct(s.win_rate)}｜场均伤害 {n0(s.per('damage'))}"]
    for g in v.groups:
        lines.append(f"— {g.label}")
        for r in g.rows:
            st = r.stat
            res = f"{st.wins}胜{st.losses}负" if st.battles > 1 else ("胜" if st.wins else ("负" if st.losses else "平"))
            lines.append(f"{r.time} {res} {r.ship}（{r.mode}{'·' + r.team if r.team else ''}）伤害 {st.damage / st.battles:,.0f} 击沉 {st.frags}")
    return "\n".join(lines)


def state_text(v: StateView) -> str:
    return f"{_title(v.who)}\n{v.heading}：{v.text}\n{v.tip}"
