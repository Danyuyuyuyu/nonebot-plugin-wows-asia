"""HTML card templates (rendered to PNG by renderer.py). All external strings are escaped."""
import math
from datetime import datetime
from html import escape

from .stats import Stat
from .views import CST, RecentView, StateView, TotalView, Identity

PINK, PINK_D, PINK_S = "#E0628C", "#B4426C", "#FFE3EC"
LAV, LAV_S = "#8C7BD8", "#ECE8FB"
INK, SUB, LINE = "#3B2F3A", "#86788A", "#F1E2E9"
WIN, LOSS, DRAW, BAD = "#3D9A74", "#CFCAD9", "#E3C27C", "#C95C6D"
TYPE_COLOR = {"战列舰": "#5B8DEF", "巡洋舰": "#A07BE0", "驱逐舰": "#EE9A4D", "航母": "#3FB0C4",
              "潜艇": "#8C93A8", "其他": "#B5ADBF"}

CSS = """
*{box-sizing:border-box}html,body{margin:0}
body{width:960px;padding:28px;background:#FBF1F5;color:#3B2F3A;font-family:"Noto Sans SC","Noto Sans CJK SC","Source Han Sans SC","Microsoft YaHei","PingFang SC",sans-serif;font-variant-numeric:tabular-nums}
.stack{display:grid;gap:22px}
.card{background:#fff;border-radius:24px;overflow:hidden;border:1px solid #F3DCE5;box-shadow:0 2px 4px rgba(180,66,108,.05),0 10px 30px rgba(180,66,108,.07)}
.head{position:relative;padding:30px 36px 28px;background:linear-gradient(120deg,#FFD6E4 0%,#FCE3F0 45%,#E9E3FF 100%);overflow:hidden}
.dots{position:absolute;inset:0;background-image:radial-gradient(rgba(255,255,255,.75) 1.6px,transparent 1.8px);background-size:22px 22px;opacity:.55}
.row{display:flex;align-items:center;position:relative}
.tag{font-size:14px;font-weight:700;letter-spacing:2px;color:#B4426C;background:rgba(255,255,255,.7);padding:5px 12px;border-radius:999px}
.stamp{margin-left:auto;font-size:13px;color:#B4426C;padding:4px 10px;border-radius:999px;background:rgba(255,255,255,.55)}
.ident{display:flex;align-items:center;gap:22px;margin-top:20px;position:relative}
.who{min-width:0;flex:1}
.name{font-size:36px;font-weight:800;letter-spacing:-.3px;line-height:1.4;padding-bottom:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.clan{color:#8C7BD8;margin-right:10px}
.meta{font-size:15px;color:#86788A;margin-top:4px;line-height:1.5}.meta b{color:#3B2F3A;font-weight:600}
.title{margin-left:auto;text-align:right;flex-shrink:0}
.title h1{margin:0;font-size:30px;font-weight:800;color:#B4426C;letter-spacing:2px}
.title .bubble{display:inline-block;margin-top:10px;background:#fff;border-radius:14px 14px 4px 14px;padding:8px 14px;font-size:14px;color:#B4426C;box-shadow:0 2px 8px rgba(180,66,108,.10)}
.body{padding:26px 32px 22px}
.hero{display:grid;grid-template-columns:270px 1fr;gap:24px;align-items:stretch}
.panel{background:#FFF8FA;border:1px solid #F1E2E9;border-radius:18px;padding:18px 20px}
.donut{display:flex;flex-direction:column;align-items:center;justify-content:center}
.legend{display:flex;gap:14px;margin-top:10px;font-size:14px;color:#86788A;flex-wrap:wrap}
.legend i{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:5px}
.kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
.kpi{background:#fff;border:1px solid #F1E2E9;border-radius:16px;padding:14px 16px}
.kpi .l{font-size:14px;color:#86788A}.kpi .v{font-size:28px;font-weight:800;margin-top:4px;letter-spacing:-.5px}
.kpi .d{font-size:13px;margin-top:2px;color:#86788A}.up{color:#2E9468!important}.down{color:#C2536A!important}
.meter{height:6px;border-radius:3px;background:#F6E7EE;margin-top:8px;overflow:hidden}.meter span{display:block;height:100%;border-radius:3px;background:#8C7BD8}
.sec{display:flex;align-items:baseline;margin:26px 0 12px}
.sec h2{margin:0;font-size:19px;font-weight:800}
.sec h2:before{content:"";display:inline-block;width:10px;height:10px;border-radius:3px;background:#E0628C;transform:rotate(45deg);margin-right:12px;vertical-align:2px;box-shadow:0 0 0 3px #FFE3EC}
.sec span{margin-left:auto;font-size:13px;color:#86788A}
.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.ships .s{display:grid;gap:12px;align-items:center;padding:7px 0;border-bottom:1px dashed #F1E2E9}.ships .s:last-child{border:0}
.sn{font-size:16px;font-weight:700;line-height:1.35;min-width:0}.sn small{display:block;font-size:12px;color:#86788A;font-weight:400;margin-top:3px}
.wr{text-align:right;font-size:16px;font-weight:800}
.tchip{display:inline-block;font-size:12px;font-weight:700;color:#fff;padding:1px 7px;border-radius:5px;margin-right:6px;vertical-align:1px}
.wbar{position:relative;height:12px;background:#F2EEF2;border-radius:6px}
.wbar span{position:absolute;left:0;top:0;bottom:0;border-radius:6px;background:#8C7BD8}
.wbar .m50{position:absolute;left:50%;top:-4px;bottom:-4px;width:2px;background:#3B2F3A;opacity:.35}
.tiers{display:grid;grid-template-columns:repeat(11,1fr);gap:10px;align-items:end}
.tc{text-align:center;min-width:0}.tc .b{font-size:12px;color:#86788A;line-height:1.4;white-space:nowrap}
.tc .col{height:120px;display:flex;align-items:flex-end;justify-content:center;margin-top:4px}
.tc .col span{display:block;width:30px;border-radius:7px 7px 3px 3px;background:linear-gradient(180deg,#B8A9F0,#8C7BD8)}
.tc .col span.z{background:#F2EEF2;height:4px!important}
.tc .t{font-size:15px;font-weight:800;margin-top:8px;line-height:1.3;border-top:1px solid #F1E2E9;padding-top:6px}
.tc .w{font-size:13px;font-weight:700;line-height:1.4}.tc .w.lo{color:#86788A;font-weight:500}
.cmp{width:100%;border-collapse:collapse;font-size:15px}
.cmp th{font-size:13px;color:#86788A;font-weight:500;text-align:right;padding:4px 0 8px}.cmp th:first-child{text-align:left}
.cmp td{padding:5px 0;text-align:right;font-weight:700;border-top:1px dashed #F1E2E9}.cmp td:first-child{text-align:left;font-weight:400;color:#86788A}
.strip{display:grid;border:1px solid #F1E2E9;border-radius:16px;background:#fff}
.strip>div{padding:12px 16px;border-right:1px dashed #F1E2E9;min-width:0}.strip>div:last-child{border:0}
.strip .l{font-size:13px;color:#86788A}.strip .v{font-size:21px;font-weight:800;margin-top:2px;line-height:1.45;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.strip .v small{font-size:13px;font-weight:500;color:#86788A;margin-left:6px}
.bt{display:grid;grid-template-columns:64px 52px 210px 1fr 64px 72px 64px;gap:12px;align-items:center;padding:10px 0;border-bottom:1px dashed #F1E2E9}
.bt:last-child{border-bottom:0}
.bt.hd{padding:4px 0 8px;font-size:12px;color:#86788A}.bt.hd div:nth-child(n+5){text-align:right}
.tm{font-size:15px;font-weight:700}.tm small{display:block;font-size:11px;color:#86788A;font-weight:400}
.res{font-size:14px;font-weight:800;color:#fff;border-radius:8px;text-align:center;padding:5px 0}
.res.m{font-size:11px}
.mtag{font-size:11px;color:#86788A;border:1px solid #F1E2E9;border-radius:5px;padding:0 5px;margin-left:6px;font-weight:400}
.num{text-align:right;font-size:16px;font-weight:800}.num small{display:block;font-size:11px;color:#86788A;font-weight:400}
.dbar{position:relative;height:10px;background:#F4EEF2;border-radius:5px}.dbar span{position:absolute;left:0;top:0;bottom:0;border-radius:5px}
.dbar i{position:absolute;left:50%;top:-4px;bottom:-4px;width:2px;background:#3B2F3A;opacity:.35}
.dtx{font-size:13px;margin-top:5px;color:#86788A;white-space:nowrap}.dtx b{color:#3B2F3A;font-size:15px;margin-right:6px}
.day{display:flex;align-items:baseline;gap:10px;padding:10px 0 4px;font-size:15px;font-weight:800;border-bottom:1px solid #F1E2E9}
.day span{font-size:13px;font-weight:400;color:#86788A}
.merged{background:#FAF7FB;border-radius:10px;padding:10px 8px;margin:4px -8px}
.note2{font-size:12px;color:#86788A;margin-top:10px;line-height:1.6}
.empty{font-size:14px;color:#86788A;padding:18px 0;text-align:center}
.state{padding:30px 36px;display:flex;gap:28px;align-items:center}
.state .ico{width:84px;height:84px;border-radius:24px;display:grid;place-items:center;flex-shrink:0}
.state h3{margin:0;font-size:24px;font-weight:800}.state p{margin:8px 0 0;font-size:15px;color:#86788A;line-height:1.7}
.state .tip{margin-top:12px;font-size:14px;background:#FFF6F9;border:1px solid #F1E2E9;border-radius:10px;padding:8px 12px}
.foot{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-top:22px;padding-top:14px;border-top:1px dashed #EBD3DD;font-size:12px;color:#86788A}
.foot b{color:#B4426C;letter-spacing:1.5px}
.state-foot{padding:0 36px 20px}
"""

def e(value) -> str:
    return escape(str(value), quote=True)


def n0(v: float | int | None) -> str:
    return "—" if v is None else f"{v:,.0f}"


def pct(v: float | None, digits: int = 1) -> str:
    return "—" if v is None else f"{v:.{digits}f}%"


def stamp(ts: int) -> str:
    return datetime.fromtimestamp(ts, CST).strftime("%Y-%m-%d %H:%M")


def page(body: str) -> str:
    return f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><style>{CSS}</style></head><body>{body}</body></html>'


def header(who: Identity, title: str, bubble: str, sub: str, stamp_text: str) -> str:
    clan = f'<span class="clan">[{e(who.clan)}]</span>' if who.clan else ""
    return f'''<div class="head"><div class="dots"></div>
<div class="row"><span class="tag">WoWS · ASIA</span><span class="stamp">{e(stamp_text)}</span></div>
<div class="ident"><div class="who"><div class="name">{clan}{e(who.nickname)}</div>
<div class="meta">账号 ID <b>{who.account_id}</b> · 亚服 · {e(sub)}</div></div>
<div class="title"><h1>{e(title)}</h1><div class="bubble">{e(bubble)}</div></div></div></div>'''


def foot(left: str, ts: int) -> str:
    return f'<div class="foot"><span><b>WOWS ASIA</b> · {e(left)}</span><span>数据来源：Wargaming 公开 API · 生成于 {stamp(ts)}</span></div>'


def donut(s: Stat, label: str) -> str:
    tot = s.battles
    r, c = 72, 2 * math.pi * 72
    segs, off = "", 0.0
    if tot:
        for v, col in ((s.wins, WIN), (s.losses, LOSS), (s.draws, DRAW)):
            if not v:
                continue
            ln = c * v / tot
            gap = 2 if v < tot else 0
            segs += (f'<circle r="{r}" cx="90" cy="90" fill="none" stroke="{col}" stroke-width="20" '
                     f'stroke-dasharray="{max(ln - gap, 0.5):.1f} {c:.1f}" stroke-dashoffset="{-off:.1f}" transform="rotate(-90 90 90)"/>')
            off += ln
    else:
        segs = f'<circle r="{r}" cx="90" cy="90" fill="none" stroke="#F2EEF2" stroke-width="20"/>'
    return f'''<div class="panel donut"><svg width="180" height="180">{segs}
<text x="90" y="80" text-anchor="middle" font-size="14" fill="{SUB}">{e(label)}</text>
<text x="90" y="112" text-anchor="middle" font-size="30" font-weight="800" fill="{INK}">{pct(s.win_rate)}</text></svg>
<div class="legend"><span><i style="background:{WIN}"></i>胜 {s.wins:,}</span><span><i style="background:{LOSS}"></i>负 {s.losses:,}</span><span><i style="background:{DRAW}"></i>平 {s.draws:,}</span></div></div>'''


def kpi(label: str, value: str, delta: str = "", cls: str = "", meter: float | None = None) -> str:
    m = f'<div class="meter"><span style="width:{min(max(meter, 0), 100):.1f}%"></span></div>' if meter is not None else ""
    d = f'<div class="d {cls}">{e(delta)}</div>' if delta else ""
    return f'<div class="kpi"><div class="l">{e(label)}</div><div class="v">{e(value)}</div>{d}{m}</div>'


def _delta(cur: float | None, base: float | None, kind: str) -> tuple[str, str]:
    """kind: rel (relative %), abs2 (absolute 2dp), pp (percentage points)."""
    if cur is None or base is None:
        return "", ""
    if kind == "rel":
        if not base:
            return "", ""
        d = (cur / base - 1) * 100
        txt = f"{abs(d):.1f}%"
    elif kind == "abs2":
        d = cur - base
        txt = f"{abs(d):.2f}"
    else:
        d = cur - base
        txt = f"{abs(d):.1f}%"
    if abs(d) < 0.05:
        return "与生涯持平", ""
    return (f"高于生涯 +{txt}", "up") if d > 0 else (f"低于生涯 −{txt}", "down")


# ---------------- total ----------------
def total_html(v: TotalView) -> str:
    s = v.random
    bubble = "累计数据整理好啦"
    if s.win_rate is not None and s.win_rate >= 55:
        bubble = "很厉害的舰长呢～"
    h = header(v.who, "总战绩", bubble, "生涯累计", f"统计于 {stamp(v.generated_at)[5:]}")
    body = '<div class="body"><div class="hero">' + donut(s, "随机胜率") + '<div class="kpis">'
    created = f"注册于 {datetime.fromtimestamp(v.created_at, CST):%Y-%m-%d}" if v.created_at else ""
    body += kpi("战斗场数", f"{s.battles:,}", created)
    body += kpi("场均伤害", n0(s.per("damage")))
    body += kpi("场均击沉", "—" if s.per("frags") is None else f"{s.per('frags'):.2f}")
    body += kpi("存活率", pct(s.survival), meter=s.survival)
    body += kpi("场均经验", n0(s.per("xp")))
    body += kpi("主炮命中率", pct(s.hit_rate), meter=s.hit_rate)
    body += "</div></div>"
    if v.types:
        tot = sum(t.battles for t in v.types) or 1
        band = "".join(f'<span style="flex:{t.battles} 0 0;min-width:6px;background:{TYPE_COLOR[t.name]}"></span>' for t in v.types)
        rows = ""
        for t in v.types:
            wr = t.wins / t.battles * 100 if t.battles else 0
            rows += f'''<div class="s" style="grid-template-columns:200px 1fr 200px"><div class="sn"><span class="tchip" style="background:{TYPE_COLOR[t.name]}">{t.name}</span><small style="display:inline;margin-left:4px">{t.battles:,} 场 · {t.battles / tot * 100:.0f}%</small></div>
<div><div class="wbar"><span style="width:{wr:.1f}%;background:{TYPE_COLOR[t.name]}"></span><div class="m50"></div></div></div>
<div class="wr">{wr:.1f}% <span style="font-size:12px;color:{SUB};font-weight:400">· 场均伤害 {t.damage / t.battles / 1000:.1f}k</span></div></div>'''
        body += '<div class="sec"><h2>舰种表现</h2><span>色带为使用占比 · 条形为胜率（0–100%，竖线为 50%）</span></div>'
        body += f'<div class="panel" style="padding:16px 20px 6px"><div style="display:flex;height:20px;border-radius:10px;overflow:hidden;gap:3px">{band}</div><div class="ships" style="margin-top:4px">{rows}</div></div>'
    if v.tiers:
        body += _tiers(v.tiers)
    rk = v.ranked
    def cell(stat: Stat | None, fn) -> str:
        return fn(stat) if stat and stat.battles else "—"
    table = '<table class="cmp"><tr><th></th><th>随机</th><th>排位</th></tr>'
    for label, fn in (("场数", lambda x: f"{x.battles:,}"), ("胜率", lambda x: pct(x.win_rate)),
                      ("场均伤害", lambda x: n0(x.per("damage"))), ("场均击沉", lambda x: f"{x.per('frags'):.2f}"),
                      ("存活率", lambda x: pct(x.survival))):
        table += f"<tr><td>{label}</td><td>{cell(s, fn)}</td><td>{cell(rk, fn)}</td></tr>"
    table += "</table>"
    div_html = ""
    for label, b, w in v.divisions:
        wr = w / b * 100
        div_html += f'''<div style="margin:10px 0 12px"><div style="display:flex;font-size:14px"><b>{label}</b><span style="color:{SUB};margin-left:8px">{b:,} 场</span><span style="margin-left:auto;font-weight:800">{wr:.1f}%</span></div>
<div class="wbar" style="margin-top:7px"><span style="width:{wr:.1f}%"></span><div class="m50"></div></div></div>'''
    div_html = (div_html + f'<div style="font-size:12px;color:{SUB}">0–100% 刻度 · 竖线为 50%</div>') if div_html else '<div class="empty">暂无组队数据</div>'
    body += f'''<div class="two"><div><div class="sec"><h2>随机 vs 排位</h2><span>生涯累计</span></div><div class="panel" style="padding:12px 20px 8px;height:216px">{table}</div></div>
<div><div class="sec"><h2>组队表现</h2><span>随机战斗胜率</span></div><div class="panel" style="padding:4px 20px 12px;height:216px">{div_html}</div></div></div>'''
    if v.records:
        body += f'<div class="strip" style="margin-top:20px;grid-template-columns:repeat({len(v.records)},1fr)">'
        for label, value, ship in v.records:
            small = f"<small>{e(ship)}</small>" if ship else ""
            body += f'<div><div class="l">{label}</div><div class="v">{value:,}{small}</div></div>'
        body += "</div>"
    body += foot("总战绩 · 生涯累计", v.generated_at) + "</div>"
    return page(f'<div class="card">{h}{body}</div>')


def _tiers(tiers: list) -> str:
    peak = max((t.battles for t in tiers), default=0) or 1
    total = sum(t.battles for t in tiers) or 1
    cols = ""
    for t in tiers:
        if t.battles:
            h = max(t.battles / peak * 120, 6)
            wr = t.wins / t.battles * 100
            bar = f'<span style="height:{h:.0f}px"></span>'
            w = f'<div class="w" style="color:{WIN if wr >= 50 else SUB}">{wr:.1f}%</div>'
            b = f"{t.battles:,}"
        else:
            bar, w, b = '<span class="z"></span>', '<div class="w lo">—</div>', "0"
        cols += f'<div class="tc"><div class="b">{b}</div><div class="col">{bar}</div><div class="t">{roman_t(t.tier)}</div>{w}</div>'
    top = max(tiers, key=lambda t: t.battles)
    hi = sum(t.battles for t in tiers if t.tier >= 8) / total * 100
    return (f'<div class="sec"><h2>等级分布</h2><span>柱高为场数 · 下方为该等级胜率 · 最常玩 {roman_t(top.tier)} 级 · VIII 级及以上占 {hi:.0f}%</span></div>'
            f'<div class="panel" style="padding:16px 20px 14px"><div class="tiers" style="grid-template-columns:repeat({len(tiers)},1fr)">{cols}</div></div>')


def roman_t(tier: int) -> str:
    from .views import roman
    return roman(tier)


# ---------------- recent ----------------
def _daily(days: list[tuple[str, Stat | None]]) -> str:
    W, H = 840, 212
    pl, pr, pt, pb = 40, 16, 46, 30
    iw, ih = W - pl - pr, H - pt - pb
    bw = iw / len(days)
    peak = max([d.battles for _, d in days if d] + [1])
    step = max(1, math.ceil(peak / 3))
    mx = step * 3
    g = ""
    for k in range(4):
        val = step * k
        y = pt + ih * (1 - val / mx)
        g += f'<line x1="{pl}" x2="{W - pr}" y1="{y:.1f}" y2="{y:.1f}" stroke="#F2E7EC"/><text x="{pl - 10}" y="{y + 4:.1f}" font-size="11" fill="{SUB}" text-anchor="end">{val}</text>'
    for i, (label, d) in enumerate(days):
        cx = pl + bw * i + bw / 2
        base = pt + ih
        if d is None:
            g += f'<text x="{cx:.1f}" y="{base - 8}" font-size="12" fill="#C0B6C3" text-anchor="middle">未记录</text>'
        elif d.battles == 0:
            g += f'<text x="{cx:.1f}" y="{base - 8}" font-size="12" fill="{SUB}" text-anchor="middle">休息</text>'
        else:
            low = d.battles < 3
            yt = pt + ih * (1 - d.battles / mx)
            hw = ih * d.wins / mx
            g += f'<g opacity="{".45" if low else "1"}"><rect x="{cx - 20:.1f}" y="{yt:.1f}" width="40" height="{base - yt:.1f}" rx="8" fill="{LOSS}"/>'
            if d.wins:
                g += f'<rect x="{cx - 20:.1f}" y="{base - hw:.1f}" width="40" height="{hw:.1f}" rx="8" fill="{WIN}"/>'
            g += "</g>"
            sub = "样本少" if low else f"{d.wins}胜{d.losses}负" + (f"{d.draws}平" if d.draws else "")
            g += f'<text x="{cx:.1f}" y="{yt - 18:.1f}" font-size="14" font-weight="800" fill="{SUB if low else INK}" text-anchor="middle">{d.win_rate:.0f}%</text>'
            g += f'<text x="{cx:.1f}" y="{yt - 5:.1f}" font-size="11" fill="{SUB}" text-anchor="middle">{sub}</text>'
        g += f'<text x="{cx:.1f}" y="{H - 8}" font-size="12" fill="{SUB}" text-anchor="middle">{label}</text>'
    return f'''<div class="panel" style="padding:10px 14px 8px"><svg width="{W}" height="{H}">{g}</svg>
<div class="legend" style="margin:2px 0 4px 36px"><span><i style="background:{WIN}"></i>胜场</span><span><i style="background:{LOSS}"></i>负/平场</span><span>柱高 = 当日场数 · 顶部为当日胜率 · 少于 3 场淡化</span></div></div>'''


def _battle_row(r) -> str:
    s = r.stat
    merged = s.battles > 1
    if merged:
        res, col = f"{s.wins}胜{s.losses}负" + (f"{s.draws}平" if s.draws else ""), LAV
    elif s.wins:
        res, col = "胜", WIN
    elif s.losses:
        res, col = "负", "#B9B2C7"
    else:
        res, col = "平", DRAW
    dmg = s.damage / s.battles
    if r.career_avg_damage:
        diff = (dmg / r.career_avg_damage - 1) * 100
        dc = WIN if diff >= 0 else BAD
        w = min(dmg / (2 * r.career_avg_damage), 1) * 100
        cmp = f'比本船均值 <span style="color:{dc};font-weight:700">{"+" if diff >= 0 else "−"}{abs(diff):.0f}%</span>'
        bar = f'<div class="dbar"><span style="width:{w:.1f}%;background:{dc}"></span><i></i></div>'
    else:
        cmp = "本船首次记录"
        bar = f'<div class="dbar"><span style="width:50%;background:{LAV}"></span></div>'
    if merged:
        alive = f"{s.survived} 存活"
    else:
        alive = f'<span style="color:{WIN}">存活</span>' if s.survived else f'<span style="color:{BAD}">沉没</span>'
    tcolor = TYPE_COLOR.get(r.ship_type, TYPE_COLOR["其他"])
    extra = f" · {s.battles} 场合计" if merged else ""
    tsub = f"<small>{e(r.time_end)}–</small>" if merged and r.time_end else ""
    frags = f"{s.frags / s.battles:.1f}" if merged else f"{s.frags}"
    return f'''<div class="bt{' merged' if merged else ''}"><div class="tm">{tsub}{e(r.time)}</div>
<div class="res{' m' if merged else ''}" style="background:{col}">{res}</div>
<div class="sn">{e(r.ship)}<small><span class="tchip" style="background:{tcolor}">{e(r.ship_type)}</span>{e(r.tier)} 级<span class="mtag">{e(r.mode)}{extra}</span></small></div>
<div>{bar}<div class="dtx"><b>{dmg:,.0f}</b>{"场均 · " if merged else ""}{cmp}</div></div>
<div class="num">{frags}<small>{"场均击沉" if merged else "击沉"}</small></div><div class="num">{s.xp / s.battles:,.0f}<small>{"场均经验" if merged else "经验"}</small></div><div class="num" style="font-size:14px">{alive}</div></div>'''


def recent_html(v: RecentView) -> str:
    s, c = v.summary, v.career
    wr = s.win_rate
    bubble = "状态平稳，继续加油～"
    if wr is not None and s.battles >= 5:
        bubble = "近 7 天表现不错哦～" if wr >= 55 else ("最近有点不顺，休息一下吧～" if wr < 45 else bubble)
    h = header(v.who, "最近战绩", bubble, f"{v.start} 至 {v.end}", f"记录自 {v.tracking_since}")
    body = '<div class="body"><div class="hero">' + donut(s, "近 7 天胜率") + '<div class="kpis">'
    if v.prev_battles is None:
        bd, bc = "随机 + 排位", ""
    else:
        d = s.battles - v.prev_battles
        bd, bc = (f"较前 7 天 {'+' if d >= 0 else '−'}{abs(d)}", "up" if d > 0 else ("down" if d < 0 else ""))
    body += kpi("战斗场数", f"{s.battles}", bd, bc)
    body += kpi("场均伤害", n0(s.per("damage")), *_delta(s.per("damage"), c.per("damage"), "rel"))
    body += kpi("场均击沉", "—" if s.per("frags") is None else f"{s.per('frags'):.2f}", *_delta(s.per("frags"), c.per("frags"), "abs2"))
    body += kpi("存活率", pct(s.survival), *_delta(s.survival, c.survival, "pp"), meter=s.survival)
    body += kpi("场均经验", n0(s.per("xp")), *_delta(s.per("xp"), c.per("xp"), "rel"))
    body += kpi("主炮命中率", pct(s.hit_rate), *_delta(s.hit_rate, c.hit_rate, "pp"), meter=s.hit_rate)
    body += "</div></div>"
    body += '<div class="sec"><h2>近 7 天每日战况</h2><span>随机 + 排位</span></div>' + _daily(v.days)
    body += '<div class="sec"><h2>最近两天场次</h2><span>时间倒序 · 伤害条中线为本船生涯场均</span></div>'
    body += '<div class="panel" style="padding:8px 20px 12px">'
    if v.groups:
        body += '<div class="bt hd"><div>时间</div><div>结果</div><div>战舰</div><div>伤害</div><div>击沉</div><div>经验</div><div>状态</div></div>'
        for g in v.groups:
            gs = g.stat
            summary = f"{gs.battles} 场 · {gs.wins} 胜 {gs.losses} 负" + (f" {gs.draws} 平" if gs.draws else "")
            body += f'<div class="day">{e(g.label)}<span>{summary}</span></div>'
            body += "".join(_battle_row(r) for r in g.rows)
        more = f"另有 {v.hidden_rows} 条更早的记录未显示。" if v.hidden_rows else ""
        body += f'<div class="note2">时间为记录到该场的快照时间，可能比实际结束晚几分钟。同一艘船在两次快照之间打了多场时，只能合并显示（灰底行）。{more}</div>'
    else:
        body += '<div class="empty">今天和昨天还没有记录到战斗</div>'
    body += "</div>" + foot("最近战绩基于战绩快照差值计算", v.generated_at) + "</div>"
    return page(f'<div class="card">{h}{body}</div>')


# ---------------- states ----------------
ICONS = {
    "hidden": ('<svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#B4426C" stroke-width="1.8" stroke-linecap="round"><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>', PINK_S, "这位舰长很低调呢"),
    "tracking": ('<svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#6E5BC4" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/></svg>', LAV_S, "正在记录中，过一会儿再来～"),
    "idle": ('<svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#6E5BC4" stroke-width="1.8" stroke-linecap="round"><path d="M4 16c3 0 3-2 6-2s3 2 6 2 3-2 4-2"/><path d="M4 20c3 0 3-2 6-2s3 2 6 2 3-2 4-2"/><path d="M12 4v7M9 7h6"/></svg>', LAV_S, "港口休息中～"),
    "quota": ('<svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#B4426C" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="8.5"/><path d="M8 12h8"/></svg>', PINK_S, "名额暂时满啦"),
    "newbie": ('<svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="#2F8566" stroke-width="1.8" stroke-linecap="round"><path d="M12 20v-8"/><path d="M12 12c0-4 3-6 7-6 0 4-3 6-7 6z"/><path d="M12 14c0-3-2-5-6-5 0 3 2 5 6 5z"/></svg>', "#E6F3EC", "新舰长你好呀"),
}


def state_html(v: StateView, now: int) -> str:
    icon, bg, bubble = ICONS[v.kind]
    h = header(v.who, v.card_title, bubble, v.sub, stamp(now)[5:])
    return page(f'''<div class="card">{h}<div class="state"><div class="ico" style="background:{bg}">{icon}</div>
<div><h3>{e(v.heading)}</h3><p>{e(v.text)}</p><div class="tip">{e(v.tip)}</div></div></div></div>''')
