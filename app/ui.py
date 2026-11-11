"""Visual system of the web interface: design tokens, CSS and small HTML components.

Everything here returns HTML strings; the Streamlit script decides where they go.
Colours: one accent (blue) for data marks, a reserved status palette that always
comes with an icon and a label, and ink tokens for every piece of text.
"""

from __future__ import annotations

from html import escape

CSS = """
<style>
:root {
  --ink: #0b0b0b; --ink-2: #52514e; --ink-3: #8a897f;
  --line: #e7e5de; --page: #f6f5f1; --card: #ffffff; --wash: #f1f0ea;
  --accent: #2a78d6; --accent-deep: #184f95; --accent-soft: #e8f1fc; --accent-track: #cde2fb;
  --good: #0ca30c; --warn: #fab219; --serious: #ec835a; --crit: #d03b3b; --neutral: #b9b7ae;
  --good-soft: #e6f5e6; --warn-soft: #fef4d9; --crit-soft: #fbe9e9; --neutral-soft: #efeee9;
  --radius: 14px;
}
header[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 1.4rem; padding-bottom: 4rem; max-width: 1320px; }

/* ---------- sidebar ---------- */
section[data-testid="stSidebar"] { border-right: 0; }
section[data-testid="stSidebar"] div[data-testid="stExpander"] details {
  background: rgba(255,255,255,.05); border: 1px solid rgba(255,255,255,.12); border-radius: 12px;
}
section[data-testid="stSidebar"] div[data-testid="stExpander"] summary { color: #eef1f7; }
.brand { display: flex; align-items: center; gap: 12px; padding: 4px 0 18px; }
.brand-mark {
  width: 40px; height: 40px; border-radius: 11px; flex: none;
  background: linear-gradient(135deg, #5b9df0 0%, #2a78d6 55%, #184f95 100%);
  display: grid; place-items: center; box-shadow: 0 6px 16px rgba(42,120,214,.35);
}
.brand-mark svg { width: 22px; height: 22px; }
.brand-name { font-weight: 700; font-size: 1.02rem; letter-spacing: -.01em; color: #fff; line-height: 1.15; }
.brand-sub { font-size: .74rem; color: #9aa6bf; letter-spacing: .02em; }
.side-label { font-size: .68rem; letter-spacing: .1em; text-transform: uppercase; color: #8794ae; margin: 14px 0 6px; font-weight: 600; }
.side-foot { font-size: .72rem; color: #8794ae; line-height: 1.5; margin-top: 18px; border-top: 1px solid rgba(255,255,255,.08); padding-top: 14px; }

/* ---------- hero ---------- */
.hero {
  position: relative; overflow: hidden; border-radius: 20px; padding: 28px 32px 26px;
  background: radial-gradient(1200px 300px at 85% -20%, rgba(91,157,240,.38), transparent 60%),
              linear-gradient(135deg, #111a2e 0%, #17294d 60%, #1c3a70 100%);
  color: #fff; margin-bottom: 18px;
}
.hero::after {
  content: ""; position: absolute; inset: 0; pointer-events: none; opacity: .5;
  background-image: radial-gradient(rgba(255,255,255,.09) 1px, transparent 1px); background-size: 22px 22px;
  mask-image: linear-gradient(90deg, transparent 35%, #000 100%);
}
.hero > * { position: relative; z-index: 1; }
.eyebrow { font-size: .7rem; letter-spacing: .14em; text-transform: uppercase; color: #a9c4f2; font-weight: 600; }
.hero h1 { font-size: 1.72rem; line-height: 1.22; font-weight: 700; letter-spacing: -.02em; margin: 10px 0 16px; max-width: 980px; color: #fff; padding: 0; }
.hero-meta { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.chip {
  display: inline-flex; align-items: center; gap: 6px; padding: 5px 11px; border-radius: 999px;
  font-size: .76rem; font-weight: 500; background: rgba(255,255,255,.1); color: #e3ebf8;
  border: 1px solid rgba(255,255,255,.12); white-space: nowrap;
}
.chip b { font-weight: 600; color: #fff; }
.state { font-weight: 600; background: #fff; color: var(--ink); border-color: #fff; }
.state .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--neutral); }
.state.done .dot { background: var(--good); }
.state.run .dot { background: var(--accent); animation: pulse 1.4s ease-in-out infinite; }
.state.wait .dot { background: var(--warn); }
.state.err .dot { background: var(--crit); }
@keyframes pulse { 0%,100% { box-shadow: 0 0 0 0 rgba(42,120,214,.5);} 50% { box-shadow: 0 0 0 6px rgba(42,120,214,0);} }

/* ---------- stepper ---------- */
.stepper { display: grid; grid-auto-flow: column; grid-auto-columns: 1fr; margin: 4px 0 22px; padding: 16px 10px 8px;
  background: var(--card); border: 1px solid var(--line); border-radius: var(--radius); }
.step { position: relative; text-align: center; padding: 0 4px; }
.step::before { content: ""; position: absolute; top: 14px; left: -50%; width: 100%; height: 2px; background: var(--line); }
.step:first-child::before { display: none; }
.step.done::before, .step.now::before { background: var(--accent); }
.node {
  position: relative; z-index: 1; width: 30px; height: 30px; border-radius: 50%; margin: 0 auto 8px;
  display: grid; place-items: center; font-size: .74rem; font-weight: 600;
  background: var(--card); color: var(--ink-3); border: 2px solid var(--line);
}
.node svg { width: 14px; height: 14px; }
.step.done .node { background: var(--accent); border-color: var(--accent); color: #fff; }
.step.now .node { border-color: var(--accent); color: var(--accent-deep); box-shadow: 0 0 0 5px var(--accent-soft); }
.step.human .node { border-radius: 9px; }
.step-name { font-size: .7rem; line-height: 1.25; color: var(--ink-2); font-weight: 500; }
.step.done .step-name { color: var(--ink); }
.step.now .step-name { color: var(--accent-deep); font-weight: 600; }
.step-kind { font-size: .58rem; letter-spacing: .08em; text-transform: uppercase; color: var(--ink-3); margin-top: 3px; }
.step-name { min-height: 2.4em; display: flex; align-items: flex-start; justify-content: center; }
.stepper-key { display: flex; gap: 16px; justify-content: flex-end; font-size: .7rem; color: var(--ink-3); margin: -14px 4px 18px; }
.stepper-key i { display: inline-block; width: 10px; height: 10px; border: 2px solid var(--neutral); margin-right: 5px; vertical-align: -1px; }
.stepper-key i.agent { border-radius: 50%; } .stepper-key i.human { border-radius: 3px; }
.mini { padding: 14px 0; border-top: 1px solid var(--line); }
.mini:first-child { border-top: 0; padding-top: 0; } .mini:last-child { padding-bottom: 0; }
.mini-title { font-size: .78rem; font-weight: 600; color: var(--ink-2); margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center; }
.mini .figure { font-size: 1.25rem; }

/* ---------- cards & tiles ---------- */
.card { background: var(--card); border: 1px solid var(--line); border-radius: var(--radius); padding: 20px 22px; height: 100%; }
.card h3 { font-size: .98rem; font-weight: 600; letter-spacing: -.01em; margin: 0 0 2px; padding: 0; color: var(--ink); }
.card .sub { font-size: .8rem; color: var(--ink-2); margin-bottom: 16px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 16px; }
.tile { background: var(--card); border: 1px solid var(--line); border-radius: var(--radius); padding: 16px 18px 15px; }
.tile-label { font-size: .76rem; color: var(--ink-2); font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tile-value { font-size: 1.9rem; font-weight: 600; letter-spacing: -.03em; line-height: 1.15; margin-top: 6px; color: var(--ink); }
.tile-value small { font-size: .95rem; font-weight: 500; color: var(--ink-3); letter-spacing: 0; }
.tile-note { font-size: .74rem; color: var(--ink-3); margin-top: 3px; }
.tile.lead { background: linear-gradient(160deg, #ffffff 0%, var(--accent-soft) 130%); border-color: #cfe0f6; }

/* ---------- charts: horizontal bars ---------- */
.bars { display: grid; row-gap: 13px; }
.bar { display: grid; grid-template-columns: minmax(150px, 34%) 1fr 62px; align-items: center; column-gap: 14px; position: relative; }
.bar-name { font-size: .82rem; color: var(--ink); font-weight: 500; line-height: 1.2; }
.bar-note { display: block; font-size: .72rem; color: var(--ink-3); font-weight: 400; margin-top: 1px; }
.bar-track { height: 14px; border-left: 1px solid #d9d7cf; }
.bar-fill { height: 14px; background: var(--accent); border-radius: 0 4px 4px 0; min-width: 2px; transition: filter .15s; }
.bar:hover .bar-fill { filter: brightness(.88); }
.bar-num { font-size: .84rem; font-weight: 600; color: var(--ink); text-align: right; font-variant-numeric: tabular-nums; }
.bar.key .bar-name { font-weight: 700; }
.tip {
  position: absolute; left: 36%; bottom: calc(100% + 4px); z-index: 20; pointer-events: none; opacity: 0; transform: translateY(4px);
  background: #111a2e; color: #fff; font-size: .74rem; line-height: 1.4; padding: 8px 11px; border-radius: 9px; max-width: 340px;
  box-shadow: 0 8px 24px rgba(17,26,46,.25); transition: opacity .12s, transform .12s;
}
.bar:hover .tip, .seg:hover .tip { opacity: 1; transform: translateY(0); }

/* ---------- charts: segmented bar ---------- */
.segbar { display: flex; gap: 2px; height: 28px; margin: 4px 0 12px; }
.seg { position: relative; border-radius: 4px; display: flex; align-items: center; padding: 0 9px; font-size: .78rem; font-weight: 600; min-width: 4px; }
.seg .tip { left: 0; }
.legend { display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: .78rem; color: var(--ink-2); }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
.swatch { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }

/* ---------- meter ---------- */
.meter { height: 8px; border-radius: 999px; background: var(--accent-track); overflow: hidden; margin: 10px 0 8px; }
.meter > i { display: block; height: 100%; border-radius: 999px; background: var(--accent); }
.figure { font-size: 1.7rem; font-weight: 600; letter-spacing: -.03em; color: var(--ink); line-height: 1.1; }
.figure small { font-size: .9rem; color: var(--ink-3); font-weight: 500; letter-spacing: 0; }

/* ---------- pills ---------- */
.pill { display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px 3px 8px; border-radius: 999px; font-size: .74rem; font-weight: 600;
  color: var(--ink); background: var(--neutral-soft); white-space: nowrap; }
.pill svg { width: 12px; height: 12px; flex: none; }
.pill.good { background: var(--good-soft); } .pill.good svg { color: var(--good); }
.pill.warn { background: var(--warn-soft); } .pill.warn svg { color: #c98500; }
.pill.crit { background: var(--crit-soft); } .pill.crit svg { color: var(--crit); }
.pill.info { background: var(--accent-soft); } .pill.info svg { color: var(--accent); }
.pill.plain svg { color: var(--ink-3); }
.tag { display: inline-block; padding: 2px 8px; border-radius: 6px; font-size: .7rem; font-weight: 600; color: var(--ink-2); background: var(--wash); border: 1px solid var(--line); }

/* ---------- lists ---------- */
.rows { display: grid; }
.row { display: flex; gap: 12px; align-items: flex-start; padding: 11px 0; border-top: 1px solid var(--line); font-size: .84rem; color: var(--ink); }
.row:first-child { border-top: 0; padding-top: 2px; }
.row .grow { flex: 1; min-width: 0; }
.row .muted, .muted { color: var(--ink-2); font-size: .78rem; }
.crit-id { flex: none; width: 34px; height: 24px; border-radius: 7px; display: grid; place-items: center; font-size: .72rem; font-weight: 700; background: var(--wash); color: var(--ink-2); }
.defs { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; }
.def { background: var(--wash); border-radius: 11px; padding: 13px 15px; }
.def b { display: block; font-size: .7rem; letter-spacing: .09em; text-transform: uppercase; color: var(--ink-3); margin-bottom: 4px; }
.def span { font-size: .85rem; color: var(--ink); line-height: 1.45; }

/* ---------- study and issue cards ---------- */
.study { background: var(--card); border: 1px solid var(--line); border-radius: var(--radius); padding: 16px 18px; margin-bottom: 4px; }
.study h4 { font-size: .93rem; font-weight: 600; line-height: 1.35; margin: 0 0 4px; padding: 0; color: var(--ink); }
.study .by { font-size: .78rem; color: var(--ink-2); margin-bottom: 10px; }
.badges { display: flex; flex-wrap: wrap; gap: 6px; }
.issue { background: var(--card); border: 1px solid var(--line); border-left: 3px solid var(--neutral); border-radius: 10px; padding: 13px 16px; margin-bottom: 10px; font-size: .84rem; line-height: 1.5; }
.issue.major { border-left-color: var(--serious); } .issue.critical { border-left-color: var(--crit); } .issue.minor { border-left-color: var(--neutral); }
.issue .head { display: flex; gap: 8px; align-items: center; margin-bottom: 6px; }
.issue .fix { color: var(--ink-2); margin-top: 6px; font-size: .8rem; }
.callout { border: 1px solid #cfe0f6; background: linear-gradient(160deg, #fff 0%, var(--accent-soft) 160%); border-radius: var(--radius); padding: 18px 22px; margin-bottom: 14px; }
.callout h3 { margin: 0 0 4px; padding: 0; font-size: 1.02rem; font-weight: 650; }
.callout p { margin: 0; color: var(--ink-2); font-size: .86rem; }
.empty { text-align: center; padding: 46px 20px; color: var(--ink-3); font-size: .88rem; border: 1px dashed #d8d6cd; border-radius: var(--radius); background: rgba(255,255,255,.5); }

/* ---------- streamlit widgets ---------- */
.stTabs [data-baseweb="tab-list"] { gap: 2px; border-bottom: 1px solid var(--line); }
.stTabs [data-baseweb="tab"] { height: 44px; padding: 0 14px; font-weight: 500; color: var(--ink-2); }
.stTabs [aria-selected="true"] { color: var(--ink); font-weight: 600; }
.stTabs [data-baseweb="tab-panel"] { padding-top: 20px; }
section[data-testid="stMain"] div[data-testid="stExpander"] details { border-radius: 12px; border-color: var(--line); background: var(--card); }
div[data-testid="stDataFrame"] { border-radius: 12px; overflow: hidden; border: 1px solid var(--line); }
.stButton > button, .stDownloadButton > button { border-radius: 10px; font-weight: 600; }
.report { background: var(--card); border: 1px solid var(--line); border-radius: var(--radius); padding: 8px 44px 30px; max-width: 900px; margin: 0 auto; }
</style>
"""

ICON = {
    "check": '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 8.5l3 3 6-7"/></svg>',
    "cross": '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M4 4l8 8M12 4l-8 8"/></svg>',
    "alert": '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M8 3.5v5.5M8 12.2v.3"/></svg>',
    "dot": '<svg viewBox="0 0 16 16" fill="currentColor"><circle cx="8" cy="8" r="3.4"/></svg>',
    "query": '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M6 6.2a2 2 0 1 1 3 1.7c-.7.4-1 .9-1 1.6M8 12.2v.3"/></svg>',
    "person": '<svg viewBox="0 0 16 16" fill="currentColor"><circle cx="8" cy="5" r="2.6"/><path d="M2.8 13.6c.5-2.6 2.6-4 5.2-4s4.7 1.4 5.2 4z"/></svg>',
    "logo": '<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 4h9l5 5v11H5z"/><path d="M9 13l2 2 4-4"/></svg>',
}
TONE_ICON = {"good": "check", "warn": "alert", "crit": "cross", "info": "dot", "plain": "dot", "unknown": "query"}


def e(value: object) -> str:
    return escape(str(value if value is not None else ""))


def pill(label: str, tone: str = "plain", icon: str | None = None) -> str:
    css = tone if tone in ("good", "warn", "crit", "info") else "plain"
    return f'<span class="pill {css}">{ICON[icon or TONE_ICON.get(tone, "dot")]}{e(label)}</span>'


def tag(label: str) -> str:
    return f'<span class="tag">{e(label)}</span>'


def brand() -> str:
    return (
        f'<div class="brand"><div class="brand-mark">{ICON["logo"]}</div><div>'
        '<div class="brand-name">PRISMAgent</div><div class="brand-sub">PRISMA 2020 · multi-agent</div></div></div>'
    )


def hero(question: str, state: tuple[str, str], chips: list[tuple[str, str]]) -> str:
    """state = (css class, label); chips = [(label, value)]."""
    meta = f'<span class="chip state {state[0]}"><span class="dot"></span>{e(state[1])}</span>'
    meta += "".join(f'<span class="chip">{e(label)} <b>{e(value)}</b></span>' for label, value in chips)
    return (
        '<div class="hero"><div class="eyebrow">Systematic review · PRISMA 2020</div>'
        f"<h1>{e(question)}</h1><div class=\"hero-meta\">{meta}</div></div>"
    )


def stepper(steps: list[dict]) -> str:
    """steps: [{name, kind ('agent' | 'human'), state ('done' | 'now' | 'todo'), n}]"""
    out = []
    for step in steps:
        human = step["kind"] == "human"
        inner = ICON["check"] if step["state"] == "done" else (ICON["person"] if human else str(step["n"]))
        out.append(
            f'<div class="step {step["state"]} {"human" if human else ""}"><div class="node">{inner}</div>'
            f'<div class="step-name">{e(step["name"])}</div></div>'
        )
    key = '<div class="stepper-key"><span><i class="agent"></i>agent</span><span><i class="human"></i>human checkpoint</span></div>'
    return f'<div class="stepper">{"".join(out)}</div>{key}'


def tiles(items: list[dict]) -> str:
    """items: [{label, value, unit?, note?, lead?}]"""
    cells = []
    for item in items:
        unit = f' <small>{e(item["unit"])}</small>' if item.get("unit") else ""
        note = f'<div class="tile-note">{e(item["note"])}</div>' if item.get("note") else ""
        cells.append(
            f'<div class="tile {"lead" if item.get("lead") else ""}"><div class="tile-label">{e(item["label"])}</div>'
            f'<div class="tile-value">{e(item["value"])}{unit}</div>{note}</div>'
        )
    return f'<div class="tiles">{"".join(cells)}</div>'


def card(title: str, body: str, sub: str = "") -> str:
    subtitle = f'<div class="sub">{e(sub)}</div>' if sub else '<div style="height:12px"></div>'
    return f'<div class="card"><h3>{e(title)}</h3>{subtitle}{body}</div>'


def bars(rows: list[dict], unit: str = "") -> str:
    """Single-series horizontal bars. rows: [{name, value, note?, tip?, key?, label?}]"""
    top = max((row["value"] for row in rows), default=0) or 1
    out = []
    for row in rows:
        note = f'<span class="bar-note">{e(row["note"])}</span>' if row.get("note") else ""
        tip = f'<div class="tip">{e(row["tip"])}</div>' if row.get("tip") else ""
        label = row.get("label") or (f"{row['value']:g}{unit}")
        out.append(
            f'<div class="bar {"key" if row.get("key") else ""}">{tip}<div class="bar-name">{e(row["name"])}{note}</div>'
            f'<div class="bar-track"><div class="bar-fill" style="width:{100 * row["value"] / top:.1f}%"></div></div>'
            f'<div class="bar-num">{e(label)}</div></div>'
        )
    return f'<div class="bars">{"".join(out)}</div>'


# status palette for the risk-of-bias figure: colour always paired with a label
STATUS = {
    "low": ("#0ca30c", "#ffffff", "Low"),
    "some concerns": ("#fab219", "#0b0b0b", "Some concerns"),
    "high": ("#d03b3b", "#ffffff", "High"),
    "unclear": ("#b9b7ae", "#0b0b0b", "Unclear"),
}


def segbar(counts: dict[str, int]) -> str:
    """One whole split into status parts (tall segmented bar) with its legend."""
    total = sum(counts.values()) or 1
    parts, legend = [], []
    for key, (fill, ink, label) in STATUS.items():
        n = counts.get(key, 0)
        legend.append(f'<span><i class="swatch" style="background:{fill}"></i>{label}</span>')
        if not n:
            continue
        share = n / total
        text = str(n) if share >= 0.07 else ""  # a block too narrow for its label prints none
        parts.append(
            f'<div class="seg" style="flex:{n} 1 0;background:{fill};color:{ink}">'
            f'<div class="tip">{label}: {n} of {total} studies ({share:.0%})</div>{text}</div>'
        )
    return f'<div class="segbar">{"".join(parts)}</div><div class="legend">{"".join(legend)}</div>'


def meter(done: int, total: int, caption: str) -> str:
    share = done / total if total else 0
    return (
        f'<div class="figure">{share:.0%} <small>{done} of {total}</small></div>'
        f'<div class="meter"><i style="width:{100 * share:.1f}%"></i></div><div class="muted">{e(caption)}</div>'
    )


def mini(title: str, body: str, right: str = "") -> str:
    """A small titled block inside a card."""
    return f'<div class="mini"><div class="mini-title"><span>{e(title)}</span>{right}</div>{body}</div>'


def compact_meter(done: int, total: int) -> str:
    share = done / total if total else 0
    return f'<div class="meter" style="margin:0"><i style="width:{100 * share:.1f}%"></i></div>'


def rows(items: list[str]) -> str:
    return f'<div class="rows">{"".join(items)}</div>'


def row(left: str, body: str, right: str = "") -> str:
    return f'<div class="row">{left}<div class="grow">{body}</div>{right}</div>'


def empty(message: str) -> str:
    return f'<div class="empty">{e(message)}</div>'


def decision_pill(decision: str) -> str:
    return {"include": pill("Include", "good"), "exclude": pill("Exclude", "crit")}.get(decision, pill("Unsure", "warn", "query"))


def rob_pill(level: str) -> str:
    tone = {"low": "good", "some concerns": "warn", "high": "crit"}.get(level, "plain")
    icon = "query" if level == "unclear" else None
    return pill(f"Risk of bias: {level}", tone, icon)
