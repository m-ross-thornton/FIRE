import copy
import json

import plotly.graph_objects as go
import streamlit as st

from calculator import CURRENT_AGE, DEATH_AGE, calculate_fire  # constants used as defaults only
from events import (
    DEFAULT_EVENTS,
    EVENT_TYPE_COLORS,
    EVENT_TYPE_LABELS,
    EVENT_TYPES,
    resolve_ages,
)
from monte_carlo import run_monte_carlo

_CFG_DEFAULTS = {
    "current_age":           CURRENT_AGE,
    "death_age":             DEATH_AGE,
    "retirement_age":        47,
    "brokerage_balance":     100_000,
    "retirement_balance":    400_000,
    "return_pre":            7.0,
    "return_post":           5.0,
    "early_withdrawal_rate": 35.0,
}

st.set_page_config(page_title="FIRE Calculator", layout="wide")
st.title("FIRE Calculator")
st.markdown(
    "Event-driven retirement financial simulator. "
    "Every financial flow — income, expenses, savings — is an **event** on the timeline."
)

# ── Session State ──────────────────────────────────────────────────────────────
if "_cfg" not in st.session_state:
    st.session_state._cfg = dict(_CFG_DEFAULTS)
if "_settings_version" not in st.session_state:
    st.session_state._settings_version = 0

_cfg = st.session_state._cfg
_v   = st.session_state._settings_version   # widget key suffix — incremented on import

if "events" not in st.session_state:
    st.session_state.events = copy.deepcopy(DEFAULT_EVENTS)
if "editing_idx" not in st.session_state:
    st.session_state.editing_idx = None
if "adding" not in st.session_state:
    st.session_state.adding = False

events = st.session_state.events  # live reference — mutations update session state

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Global Settings")

    st.subheader("Age Range")
    current_age = st.number_input("Current Age", min_value=1, max_value=80,
                                  value=int(_cfg.get("current_age", CURRENT_AGE)), step=1,
                                  key=f"current_age_{_v}")
    death_age   = st.number_input("Life Expectancy", min_value=50, max_value=120,
                                  value=int(_cfg.get("death_age", DEATH_AGE)), step=1,
                                  key=f"death_age_{_v}")
    _ret_default = max(int(current_age), min(int(min(80, death_age)), int(_cfg.get("retirement_age", 47))))
    retirement_age = st.slider(
        "Retirement Age",
        min_value=int(current_age),
        max_value=int(min(80, death_age)),
        value=_ret_default,
        key=f"retirement_age_{_v}",
    )

    st.subheader("Starting Balances")
    brokerage_balance  = st.number_input("Brokerage Balance ($)",  min_value=0,
                                         value=int(_cfg.get("brokerage_balance",  100_000)), step=1_000,
                                         key=f"brokerage_{_v}")
    retirement_balance = st.number_input("Retirement Balance ($)", min_value=0,
                                         value=int(_cfg.get("retirement_balance", 400_000)), step=1_000,
                                         key=f"retirement_{_v}")

    st.subheader("Growth Rates")
    return_pre  = st.slider("Pre-Retirement Return (%)",  0.0, 12.0,
                            float(_cfg.get("return_pre",  7.0)), 0.1, key=f"return_pre_{_v}") / 100
    return_post = st.slider("Post-Retirement Return (%)", 0.0, 12.0,
                            float(_cfg.get("return_post", 5.0)), 0.1, key=f"return_post_{_v}") / 100

    st.subheader("Early Withdrawal")
    early_withdrawal_rate = st.slider(
        "Early Withdrawal Rate (%)", 0, 50, int(_cfg.get("early_withdrawal_rate", 35)), 1,
        key=f"ewr_{_v}",
        help=(
            "Combined IRS 10% penalty + estimated income tax on retirement account "
            "withdrawals before age 60 (59½ rule). Applied only when brokerage is "
            "exhausted. Default 35% = 10% penalty + 25% marginal tax."
        ),
    ) / 100

    st.divider()
    st.subheader("Settings")

    # ── Export ────────────────────────────────────────────────────────────────
    _export_data = {
        "current_age":           int(current_age),
        "death_age":             int(death_age),
        "retirement_age":        retirement_age,
        "brokerage_balance":     int(brokerage_balance),
        "retirement_balance":    int(retirement_balance),
        "return_pre":            round(return_pre  * 100, 1),
        "return_post":           round(return_post * 100, 1),
        "early_withdrawal_rate": round(early_withdrawal_rate * 100, 1),
        "events":                events,
    }
    st.download_button(
        "⬇ Export Settings",
        data=json.dumps(_export_data, indent=2),
        file_name="my_plan.json",
        mime="application/json",
        use_container_width=True,
    )

    # ── Import ────────────────────────────────────────────────────────────────
    uploaded = st.file_uploader("Import Settings", type=["json"], label_visibility="collapsed")
    if uploaded is not None:
        _file_hash = hash(uploaded.getvalue())
        if st.session_state.get("_last_import_hash") != _file_hash:
            try:
                _imported = json.loads(uploaded.getvalue())
                st.session_state._cfg = {**_CFG_DEFAULTS, **_imported}
                st.session_state.events = _imported.get("events", copy.deepcopy(DEFAULT_EVENTS))
                st.session_state._settings_version += 1
                st.session_state._last_import_hash = _file_hash
                st.rerun()
            except Exception as _e:
                st.error(f"Invalid settings file: {_e}")



# ── Helper: event form ─────────────────────────────────────────────────────────
_START_OPTIONS = ["Specific Age", "At Retirement (first retired year)"]
_END_OPTIONS   = ["Specific Age", "At Retirement (last working year)", "Until Death"]
_START_OPT_IDX = {"specific": 0, "retirement": 1}
_END_OPT_IDX   = {"specific": 0, "retirement": 1, "death": 2}
_START_OPT_KEY = {v: k for k, v in _START_OPT_IDX.items()}
_END_OPT_KEY   = {v: k for k, v in _END_OPT_IDX.items()}


def _event_form(form_key: str, defaults: dict, submit_label: str,
                retirement_age: int, current_age: int, death_age: int):
    """
    Render a bordered form for adding/editing an event.
    Returns (save_clicked, cancel_clicked, values_dict).
    """
    # Resolve legacy boolean flags so old session-state events still open correctly
    cur_start_mode = defaults.get("start_mode") or ("retirement" if defaults.get("start_is_retirement") else "specific")
    cur_end_mode   = defaults.get("end_mode")   or ("retirement" if defaults.get("end_is_retirement")   else "specific")

    with st.form(form_key, border=True):
        c1, c2 = st.columns(2)
        with c1:
            name    = st.text_input("Name *", value=defaults["name"],
                                    placeholder="e.g. Salary, Mortgage, VA Disability")
            type_   = st.selectbox("Type *", options=EVENT_TYPES,
                                   index=EVENT_TYPES.index(defaults["type"]) if defaults["type"] in EVENT_TYPES else 0,
                                   format_func=lambda t: EVENT_TYPE_LABELS.get(t, t))
            monthly = st.number_input("Monthly Amount ($) *", value=float(defaults["monthly_amount"]),
                                      min_value=0.0, step=50.0, format="%.0f")
            rate    = st.number_input("Annual Rate (%/yr)", value=float(defaults["annual_rate"]),
                                      min_value=-20.0, max_value=20.0, step=0.5, format="%.1f",
                                      help="Compound annual % change — raises (+), inflation (+), payoff schedule (−).")
        with c2:
            start_opt = st.radio("Start Age", _START_OPTIONS, horizontal=True,
                                 index=_START_OPT_IDX.get(cur_start_mode, 0))
            start_mode = _START_OPT_KEY[_START_OPTIONS.index(start_opt)]
            if start_mode == "specific":
                start = st.number_input("Age", value=int(defaults["start_age"]),
                                        min_value=int(current_age), max_value=int(death_age), step=1,
                                        key=f"{form_key}_start")
            else:
                st.caption(f"Age **{retirement_age + 1}** — first retired year (follows Retirement Age slider)")
                start = retirement_age + 1

            st.markdown("")  # spacer
            end_opt = st.radio("End Age", _END_OPTIONS, horizontal=True,
                               index=_END_OPT_IDX.get(cur_end_mode, 0))
            end_mode = _END_OPT_KEY[_END_OPTIONS.index(end_opt)]
            if end_mode == "specific":
                end = st.number_input("Age ", value=int(defaults["end_age"]),
                                      min_value=int(current_age), max_value=int(death_age), step=1,
                                      key=f"{form_key}_end")
            elif end_mode == "retirement":
                st.caption(f"Age **{retirement_age}** — last working year (follows Retirement Age slider)")
                end = retirement_age
            else:
                st.caption(f"Age **{death_age}** — life expectancy (follows Life Expectancy input)")
                end = death_age

        notes = st.text_input("Notes (optional)", value=defaults.get("notes", ""))
        s_col, c_col = st.columns(2)
        save   = s_col.form_submit_button(submit_label, type="primary", use_container_width=True)
        cancel = c_col.form_submit_button("Cancel", use_container_width=True)

    values = {
        "name": name,
        "type": type_,
        "monthly_amount": monthly,
        "start_age": start,
        "end_age": end,
        "start_mode": start_mode,
        "end_mode": end_mode,
        "annual_rate": rate,
        "notes": notes,
    }
    return save, cancel, values


def _validate(v: dict) -> str | None:
    if not v["name"].strip():
        return "Event name is required."
    if v["start_age"] > v["end_age"]:
        return "Start Age must be ≤ End Age."
    return None


# ── Events Section ─────────────────────────────────────────────────────────────
st.subheader("Timeline Events")
st.caption(
    "Each event is a financial flow active between **Start Age** and **End Age** (inclusive). "
    "Income/Expense events affect monthly cashflow and the Net Budget. "
    "Contribution events credit an account directly and are subtracted from the budget. "
    "**Annual Rate** compounds the monthly amount each year."
)

# Top action buttons
btn_col1, btn_col2, _ = st.columns([1, 1, 5])
if btn_col1.button("＋ Add Event", type="primary", use_container_width=True):
    st.session_state.adding = True
    st.session_state.editing_idx = None
    st.rerun()
if btn_col2.button("Reset Defaults", use_container_width=True):
    st.session_state.events = copy.deepcopy(DEFAULT_EVENTS)
    st.session_state.editing_idx = None
    st.session_state.adding = False
    st.rerun()

# ── Add form ───────────────────────────────────────────────────────────────────
if st.session_state.adding:
    st.markdown("#### New Event")
    _defaults_new = {
        "name": "", "type": "expense", "monthly_amount": 1000.0,
        "start_age": int(current_age), "end_age": int(death_age),
        "start_mode": "specific", "end_mode": "specific",
        "annual_rate": 0.0, "notes": "",
    }
    save, cancel, vals = _event_form("add_form", _defaults_new, "Add Event",
                                     retirement_age, int(current_age), int(death_age))
    if cancel:
        st.session_state.adding = False
        st.rerun()
    if save:
        err = _validate(vals)
        if err:
            st.error(err)
        else:
            vals["name"] = vals["name"].strip()
            vals["notes"] = vals["notes"].strip()
            events.append(vals)
            st.session_state.adding = False
            st.rerun()

# ── Event list ─────────────────────────────────────────────────────────────────
st.divider()

# Column header
_W = [0.14, 0.24, 0.13, 0.17, 0.11, 0.08, 0.07, 0.06]
hdr = st.columns(_W)
for label, col in zip(["Type", "Name", "Monthly", "Ages", "Rate/yr", "Notes", "", ""], hdr):
    if label:
        col.markdown(f"<span style='font-size:0.78em; color:gray'>{label}</span>", unsafe_allow_html=True)

for i, ev in enumerate(events):
    color = EVENT_TYPE_COLORS.get(ev["type"], "#888")
    type_label = EVENT_TYPE_LABELS.get(ev["type"], ev["type"])
    rate_str = f"{ev['annual_rate']:+.1f}%" if ev["annual_rate"] != 0 else "—"

    row = st.columns(_W)
    row[0].markdown(
        f'<span style="color:{color}; font-size:0.82em">● {type_label}</span>',
        unsafe_allow_html=True,
    )
    row[1].markdown(f"**{ev['name']}**")
    row[2].markdown(f"${ev['monthly_amount']:,.0f}/mo")
    sm = ev.get("start_mode") or ("retirement" if ev.get("start_is_retirement") else "specific")
    em = ev.get("end_mode")   or ("retirement" if ev.get("end_is_retirement")   else "specific")
    sa_label = "**Ret.+1**" if sm == "retirement" else str(ev["start_age"])
    ea_label = "**Ret.**"   if em == "retirement" else ("**Death**" if em == "death" else str(ev["end_age"]))
    row[3].markdown(f"{sa_label} → {ea_label}")
    row[4].markdown(rate_str)
    row[5].markdown(
        f"<span style='font-size:0.82em; color:gray'>{ev.get('notes','')}</span>",
        unsafe_allow_html=True,
    )

    if row[6].button("Edit", key=f"edit_btn_{i}", use_container_width=True):
        st.session_state.editing_idx = i
        st.session_state.adding = False
        st.rerun()

    if row[7].button("✕", key=f"del_btn_{i}", use_container_width=True):
        events.pop(i)
        # keep editing_idx consistent after deletion
        if st.session_state.editing_idx == i:
            st.session_state.editing_idx = None
        elif st.session_state.editing_idx is not None and st.session_state.editing_idx > i:
            st.session_state.editing_idx -= 1
        st.rerun()

    # Inline edit form appears immediately below the selected row
    if st.session_state.editing_idx == i:
        st.markdown(f"#### Edit: {ev['name']}")
        save, cancel, vals = _event_form(f"edit_form_{i}", ev, "Save Changes",
                                          retirement_age, int(current_age), int(death_age))
        if cancel:
            st.session_state.editing_idx = None
            st.rerun()
        if save:
            err = _validate(vals)
            if err:
                st.error(err)
            else:
                vals["name"] = vals["name"].strip()
                vals["notes"] = vals["notes"].strip()
                events[i] = vals
                st.session_state.editing_idx = None
                st.rerun()


# ── Calculate ──────────────────────────────────────────────────────────────────
_resolved_events = resolve_ages(events, retirement_age, int(death_age))
data = calculate_fire(
    _resolved_events,
    brokerage_balance, retirement_balance,
    retirement_age, return_pre, return_post, early_withdrawal_rate,
    current_age=int(current_age), death_age=int(death_age),
)
df = data["df"]


# ── Metrics ────────────────────────────────────────────────────────────────────
st.divider()
status_label = "✅ Funded through life expectancy" if data["success"] else "⚠️ Funds depleted before life expectancy"
st.metric("Simulation Status", status_label, f"Ending Balance: ${data['final_amount']:,.0f}")


# ── Charts ─────────────────────────────────────────────────────────────────────
tab_nw, tab_cf, tab_timeline, tab_mc = st.tabs(["Net Worth", "Cash Flows", "Event Timeline", "Monte Carlo"])

# ── Net Worth ──────────────────────────────────────────────────────────────────
with tab_nw:
    fig_nw = go.Figure()
    fig_nw.add_trace(go.Scatter(
        x=df["Age"], y=df["Brokerage"], name="Brokerage",
        stackgroup="one",
        fillcolor="rgba(56, 189, 248, 0.5)",
        line=dict(color="#38bdf8", width=1),
    ))
    fig_nw.add_trace(go.Scatter(
        x=df["Age"], y=df["Retirement"], name="Retirement",
        stackgroup="one",
        fillcolor="rgba(129, 140, 248, 0.5)",
        line=dict(color="#818cf8", width=1),
    ))

    fig_nw.add_vline(x=retirement_age, line_width=2, line_dash="dash", line_color="#f472b6",
                     annotation_text="Retirement", annotation_position="top left")
    fig_nw.update_layout(
        title="Net Worth Projection",
        xaxis_title="Age", yaxis_title="Balance ($)",
        hovermode="x unified", height=500,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig_nw, use_container_width=True)


# ── Cash Flows ─────────────────────────────────────────────────────────────────
with tab_cf:
    fig_cf = go.Figure()

    fig_cf.add_trace(go.Scatter(
        x=df["Age"], y=df["Mo Income"], name="Income",
        fill="tozeroy", fillcolor="rgba(74, 222, 128, 0.25)",
        line=dict(color="#4ade80", width=2),
    ))
    fig_cf.add_trace(go.Scatter(
        x=df["Age"], y=df["Mo Expenses"], name="Expenses",
        fill="tozeroy", fillcolor="rgba(248, 113, 113, 0.25)",
        line=dict(color="#f87171", width=2),
    ))
    fig_cf.add_trace(go.Scatter(
        x=df["Age"], y=df["Mo Ret Contrib"], name="Retirement Contributions",
        line=dict(color="#818cf8", width=2, dash="dash"),
    ))
    fig_cf.add_trace(go.Scatter(
        x=df["Age"], y=df["Mo Brk Contrib"], name="Brokerage Contributions",
        line=dict(color="#38bdf8", width=2, dash="dash"),
    ))

    # Net Budget line — positive = surplus, negative = drawing from savings
    fig_cf.add_hline(y=0, line_width=1, line_color="rgba(255,255,255,0.25)")
    fig_cf.add_trace(go.Scatter(
        x=df["Age"], y=df["Mo Net Budget"],
        name="Net Budget (+ surplus / − deficit)",
        fill="tozeroy", fillcolor="rgba(251, 191, 36, 0.12)",
        line=dict(color="#fbbf24", width=2.5),
    ))

    if df["Mo Penalty"].abs().max() > 0:
        fig_cf.add_trace(go.Scatter(
            x=df["Age"], y=-df["Mo Penalty"],
            name="Early Withdrawal Penalty",
            fill="tozeroy", fillcolor="rgba(239, 68, 68, 0.15)",
            line=dict(color="#ef4444", width=2, dash="dot"),
        ))

    fig_cf.add_vline(x=retirement_age, line_width=2, line_dash="dash", line_color="#f472b6",
                     annotation_text="Retirement", annotation_position="top left")
    if early_withdrawal_rate > 0:
        fig_cf.add_vline(x=60, line_width=1, line_dash="dot", line_color="#f97316",
                         annotation_text="59½ (no penalty)", annotation_position="top right")
    fig_cf.update_layout(
        title="Monthly Cash Flows  ·  Net Budget = Income − Expenses − Contributions",
        xaxis_title="Age", yaxis_title="Monthly Amount ($)",
        hovermode="x unified", height=450,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig_cf, use_container_width=True)

# ── Event Timeline (Gantt) ─────────────────────────────────────────────────────
with tab_timeline:
    if not events:
        st.info("No events to display.")
    else:
        fig_gantt = go.Figure()
        seen_types: set = set()

        for ev in _resolved_events:
            type_str = str(ev.get("type", "expense"))
            color    = EVENT_TYPE_COLORS.get(type_str, "#888")
            label    = EVENT_TYPE_LABELS.get(type_str, type_str)
            monthly  = ev.get("monthly_amount", 0)
            rate     = ev.get("annual_rate", 0.0)
            sa, ea   = int(ev["start_age"]), int(ev["end_age"])
            notes_str = str(ev.get("notes", ""))

            bar_text = f"${monthly:,.0f}/mo"
            if rate and rate != 0:
                bar_text += f"  {rate:+.1f}%/yr"

            fig_gantt.add_trace(go.Bar(
                name=label,
                y=[ev["name"]],
                x=[ea - sa + 1],
                base=[sa],
                orientation="h",
                marker=dict(color=color, opacity=0.75, line=dict(color=color, width=1)),
                text=bar_text,
                textposition="inside",
                insidetextanchor="middle",
                showlegend=False,
                hovertemplate=(
                    f"<b>{ev['name']}</b><br>"
                    f"Type: {label}<br>"
                    f"Ages {sa} – {ea}<br>"
                    f"${monthly:,.0f}/mo · {rate:.1f}%/yr"
                    + (f"<br>{notes_str}" if notes_str else "")
                    + "<extra></extra>"
                ),
            ))

            if type_str not in seen_types:
                seen_types.add(type_str)
                fig_gantt.add_trace(go.Bar(
                    name=label, x=[0], y=[""],
                    orientation="h",
                    marker_color=color,
                    showlegend=True,
                ))

        fig_gantt.add_vline(x=retirement_age, line_width=2, line_dash="dash",
                            line_color="#f472b6", annotation_text="Retirement",
                            annotation_position="top right")

        fig_gantt.update_layout(
            barmode="overlay",
            title="Event Timeline",
            xaxis=dict(title="Age", range=[int(current_age) - 1, int(death_age) + 1]),
            yaxis=dict(autorange="reversed"),
            height=max(280, len(events) * 48 + 120),
            margin=dict(l=10, r=20, t=50, b=40),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig_gantt, use_container_width=True)


# ── Simulation Details ─────────────────────────────────────────────────────────
with st.expander("Simulation Details (Year-by-Year)"):
    money_cols = [
        "Brokerage", "Retirement", "Total",
        "Mo Income", "Mo Expenses", "Mo Ret Contrib", "Mo Brk Contrib",
        "Mo Net Budget", "Mo Penalty",
    ]
    fmt = {c: "${:,.0f}" for c in money_cols}
    st.dataframe(df.style.format(fmt), use_container_width=True)


# ── Monte Carlo ────────────────────────────────────────────────────────────────
with tab_mc:
    st.caption(
        "Samples portfolio returns each year from a normal distribution. "
        "Event rates are sampled once per simulation (a persistently different "
        "inflation or growth rate for the full horizon). "
        "The base scenario line uses your exact sidebar values."
    )

    ctrl, results_col = st.columns([1, 2])

    with ctrl:
        n_sims = st.slider("Simulations", 100, 2000, 500, 100)
        return_floor_pct = st.slider("Annual return floor (%)", -80, 0, -50, 5)
        return_floor = return_floor_pct / 100

        st.markdown("**Portfolio Returns**")
        vary_pre  = st.checkbox("Pre-retirement return",  value=True)
        pre_std   = st.number_input("Std dev (%/yr)", 0.1, 30.0, 10.0, 0.5,
                                    key="mc_pre_std",  disabled=not vary_pre)
        vary_post = st.checkbox("Post-retirement return", value=True)
        post_std  = st.number_input("Std dev (%/yr)", 0.1, 30.0,  7.0, 0.5,
                                    key="mc_post_std", disabled=not vary_post)

        _variable_events = [ev for ev in _resolved_events if ev.get("annual_rate", 0) != 0]
        event_stds: dict = {}
        if _variable_events:
            st.markdown("**Event Rates**")
            for ev in _variable_events:
                vary_ev = st.checkbox(
                    f"{ev['name']}  ({ev['annual_rate']:+.1f}%/yr)",
                    key=f"mc_ev_{ev['name']}",
                )
                ev_std = st.number_input(
                    "Std dev (%/yr)", 0.1, 10.0, 1.0, 0.5,
                    key=f"mc_evstd_{ev['name']}", disabled=not vary_ev,
                )
                if vary_ev:
                    event_stds[ev["name"]] = ev_std

        st.markdown("")
        run_btn = st.button("Run Monte Carlo", type="primary", use_container_width=True)

    if run_btn:
        with results_col:
            with st.spinner(f"Running {n_sims:,} simulations…"):
                st.session_state.mc_results = run_monte_carlo(
                    _resolved_events,
                    brokerage_balance, retirement_balance,
                    retirement_age, return_pre, return_post, early_withdrawal_rate,
                    int(current_age), int(death_age),
                    n_sims,
                    (pre_std  / 100) if vary_pre  else 0.0,
                    (post_std / 100) if vary_post else 0.0,
                    return_floor,
                    event_stds,
                )

    with results_col:
        mc = st.session_state.get("mc_results")
        if mc is None:
            st.info("Configure settings on the left and click **Run Monte Carlo**.")
        else:
            pcts = mc["percentiles"]
            ages_mc = mc["ages"]
            success_pct = mc["success_rate"] * 100

            color = "#4ade80" if success_pct >= 80 else ("#facc15" if success_pct >= 50 else "#f87171")
            st.markdown(
                f"<h2 style='color:{color}; margin:0'>{success_pct:.1f}%</h2>"
                f"<p style='color:gray; margin:0'>of simulations remain solvent through life expectancy</p>",
                unsafe_allow_html=True,
            )
            st.markdown("")

            # ── Percentile fan chart ───────────────────────────────────────────
            fig_mc = go.Figure()

            def _band(lo, hi, fill_color, name):
                x = ages_mc + ages_mc[::-1]
                y = pcts[hi] + pcts[lo][::-1]
                fig_mc.add_trace(go.Scatter(
                    x=x, y=y, fill="toself", fillcolor=fill_color,
                    line=dict(width=0), name=name, hoverinfo="skip",
                ))

            _band(10, 90, "rgba(99,110,250,0.12)", "10th – 90th pct")
            _band(25, 75, "rgba(99,110,250,0.25)", "25th – 75th pct")

            fig_mc.add_trace(go.Scatter(
                x=ages_mc, y=pcts[50], name="Median (50th)",
                line=dict(color="#636efa", width=2.5),
            ))
            fig_mc.add_trace(go.Scatter(
                x=df["Age"], y=df["Total"], name="Base scenario",
                line=dict(color="white", width=1.5, dash="dash"),
            ))

            fig_mc.add_vline(x=retirement_age, line_width=2, line_dash="dash",
                             line_color="#f472b6", annotation_text="Retirement",
                             annotation_position="top left")
            fig_mc.update_layout(
                title="Net Worth — Percentile Bands",
                xaxis_title="Age", yaxis_title="Total Net Worth ($)",
                hovermode="x unified", height=420,
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            )
            st.plotly_chart(fig_mc, use_container_width=True)

            # ── Final balance histogram ────────────────────────────────────────
            fig_hist = go.Figure(go.Histogram(
                x=mc["final_totals"], nbinsx=60,
                marker_color="#636efa", opacity=0.75,
                name="Final balance",
            ))
            fig_hist.add_vline(
                x=float(pcts[50][-1]), line_width=2, line_dash="dash",
                line_color="white", annotation_text="Median",
                annotation_position="top right",
            )
            fig_hist.update_layout(
                title=f"Distribution of Final Net Worth at Age {int(death_age)}",
                xaxis_title="Net Worth ($)", yaxis_title="Simulations",
                height=300, showlegend=False,
            )
            st.plotly_chart(fig_hist, use_container_width=True)


