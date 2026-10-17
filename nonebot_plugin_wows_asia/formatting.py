"""Plain-text fallbacks (used when image rendering is disabled or fails)."""
from .cards import n0, pct
from .views import BattleDetailView, BattleRow, BattlesView, RecentView, StateView, TotalView, roman


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


def _res(st) -> str:
    if st.battles > 1:
        return f"{st.wins}胜{st.losses}负" + (f"{st.draws}平" if st.draws else "")
    return "胜" if st.wins else ("负" if st.losses else "平")


def battle_line(r: BattleRow) -> str:
    st, n = r.stat, r.stat.battles
    dmg = st.damage / n
    cmp = f"（本船均值 {'+' if dmg >= r.career_avg_damage else '−'}{abs(dmg / r.career_avg_damage - 1) * 100:.0f}%）" \
        if r.career_avg_damage else ""
    when = f"{r.date + ' ' if r.date else ''}{r.time}"
    mode = r.mode + (f"·{r.team}" if r.team else "")
    if n > 1:
        return (f"{when} {_res(st)} {r.ship}（{mode}，{n} 场合计）场均伤害 {dmg:,.0f}{cmp} "
                f"场均击沉 {st.frags / n:.1f} 存活 {st.survived}/{n}")
    return (f"{when} {_res(st)} {r.ship}（{mode}）伤害 {dmg:,.0f}{cmp} 击沉 {st.frags} 经验 {st.xp:,} "
            f"{'存活' if st.survived else '沉没'}")


def battles_text(v: BattlesView, with_title: bool = True) -> str:
    s = v.summary
    head = f"【场次 · {v.desc}】"
    lines = [_title(v.who), head] if with_title else [v.who.nickname + head]
    lines += [
              f"{s.battles} 场 {s.wins}胜{s.losses}负｜胜率 {pct(s.win_rate)}｜场均伤害 {n0(s.per('damage'))}"
              f"｜场均击沉 {'—' if s.per('frags') is None else format(s.per('frags'), '.2f')}｜存活率 {pct(s.survival)}"]
    rows = v.rows if not v.groups else [r for g in v.groups for r in g.rows]
    if v.groups:
        for g in v.groups:
            lines.append(f"— {g.label}")
            lines += [battle_line(r) for r in g.rows]
    else:
        lines += [f"{i}. {battle_line(r)}" for i, r in enumerate(rows, 1)]
    if v.hidden_rows:
        lines.append(f"共 {v.hidden_rows + len(rows)} 场符合条件，只列出前 {len(rows)} 场")
    return "\n".join(lines)


def battle_text(v: BattleDetailView, with_title: bool = True) -> str:
    r, rec = v.row, v.record
    s, n = rec.stat, rec.stat.battles
    head = f"【单场 · {v.position}】{v.when}"
    lines = [_title(v.who), head] if with_title else [v.who.nickname + head]
    lines.append(battle_line(r))
    if rec.full:
        f = (lambda x: f"{x / n:.1f}") if n > 1 else (lambda x: f"{x:,}")  # noqa: E731
        extra = [f"侦察伤害 {s.scouting / n:,.0f}", f"潜在伤害 {s.potential / n:,.0f}", f"点亮 {f(s.spotted)}"]
        if s.shots:
            extra.append(f"主炮命中率 {s.hits / s.shots * 100:.1f}%")
        if s.torp_shots:
            extra.append(f"鱼雷命中率 {s.torp_hits / s.torp_shots * 100:.1f}%")
        if s.planes:
            extra.append(f"击落飞机 {f(s.planes)}")
        lines.append("｜".join(extra))
    if rec.best:
        from .storage import BEST_DAMAGE, BEST_FRAGS, BEST_XP
        got = [label for bit, label in ((BEST_DAMAGE, "伤害"), (BEST_FRAGS, "击沉"), (BEST_XP, "经验")) if rec.best & bit]
        lines.append("本船新纪录：" + "、".join(got))
    if v.rank:
        lines.append(f"伤害在本船近 {v.rank[1]} 场中排第 {v.rank[0]}")
    if v.others:
        lines.append(f"这个条件下共 {v.others + 1} 场，只显示了 1 场；查看全部请用“场次”加同样的条件")
    return "\n".join(lines)


def total_caption(v: TotalView) -> str:
    s = v.random
    text = (f"{v.who.nickname} 总战绩：随机 {s.battles:,} 场，胜率 {pct(s.win_rate, 2)}，场均伤害 {n0(s.per('damage'))}，"
            f"场均击沉 {'—' if s.per('frags') is None else format(s.per('frags'), '.2f')}，存活率 {pct(s.survival)}")
    if v.ranked:
        text += f"；排位 {v.ranked.battles:,} 场，胜率 {pct(v.ranked.win_rate)}"
    return text


def recent_caption(v: RecentView) -> str:
    s = v.summary
    text = (f"{v.who.nickname} 近 7 天（{v.start} 至 {v.end}）：{s.battles} 场，胜率 {pct(s.win_rate)}，"
            f"场均伤害 {n0(s.per('damage'))}，存活率 {pct(s.survival)}")
    for g in v.groups:
        text += f"\n— {g.label}：" + "；".join(battle_line(r) for r in g.rows[:6])
    return text
