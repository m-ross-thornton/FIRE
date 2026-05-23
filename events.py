import pandas as pd

EVENT_TYPES = [
    "income",
    "expense",
    "retirement_contribution",
    "brokerage_contribution",
]

EVENT_TYPE_LABELS = {
    "income": "Income",
    "expense": "Expense",
    "retirement_contribution": "Retirement (401k/IRA/HSA)",
    "brokerage_contribution": "Brokerage Savings",
}

EVENT_TYPE_COLORS = {
    "income": "#4ade80",
    "expense": "#f87171",
    "retirement_contribution": "#818cf8",
    "brokerage_contribution": "#38bdf8",
}

# start_mode / end_mode values:
#   "specific"   — use the stored start_age / end_age integer
#   "retirement" — substitute retirement_age (start) or retirement_age (end) at resolve time
#   "death"      — substitute death_age at resolve time (end only)
DEFAULT_EVENTS = [
    {
        "name": "Brokerage Savings",
        "type": "brokerage_contribution",
        "monthly_amount": 4000.0,
        "start_age": 40,
        "end_age": 47,
        "start_mode": "specific",
        "end_mode": "retirement",
        "annual_rate": 0.0,
        "notes": "Pre-retirement taxable savings",
    },
    {
        "name": "HSA",
        "type": "retirement_contribution",
        "monthly_amount": 800.0,
        "start_age": 40,
        "end_age": 47,
        "start_mode": "specific",
        "end_mode": "retirement",
        "annual_rate": 0.0,
        "notes": "IRS limit ~$3,400/mo combined",
    },
    {
        "name": "Living Expenses",
        "type": "expense",
        "monthly_amount": 5000.0,
        "start_age": 40,
        "end_age": 47,
        "start_mode": "specific",
        "end_mode": "retirement",
        "annual_rate": 3.0,
        "notes": "3% annual cost-of-living increase",
    },
    {
        "name": "VA Disability",
        "type": "income",
        "monthly_amount": 2500.0,
        "start_age": 40,
        "end_age": 95,
        "start_mode": "specific",
        "end_mode": "death",
        "annual_rate": 0.0,
        "notes": "Tax-free",
    },
    {
        "name": "DS3",
        "type": "income",
        "monthly_amount": 12000.0,
        "start_age": 40,
        "end_age": 42,
        "start_mode": "specific",
        "end_mode": "specific",
        "annual_rate": 1.0,
        "notes": "",
    },
    {
        "name": "DS4",
        "type": "income",
        "monthly_amount": 13500.0,
        "start_age": 43,
        "end_age": 47,
        "start_mode": "specific",
        "end_mode": "retirement",
        "annual_rate": 1.0,
        "notes": "",
    },
    {
        "name": "Mortgage",
        "type": "expense",
        "monthly_amount": 4500.0,
        "start_age": 40,
        "end_age": 70,
        "start_mode": "specific",
        "end_mode": "specific",
        "annual_rate": 0.0,
        "notes": "",
    },
    {
        "name": "Living Expenses - no kids",
        "type": "expense",
        "monthly_amount": 3000.0,
        "start_age": 47,
        "end_age": 95,
        "start_mode": "retirement",
        "end_mode": "death",
        "annual_rate": 3.0,
        "notes": "",
    },
]


def resolve_ages(events: list, retirement_age: int, death_age: int) -> list:
    """
    Return a copy of events with start_mode / end_mode flags resolved to concrete ages.

    start_mode:
      "specific"    → use stored start_age
      "retirement"  → retirement_age + 1  (first retired year, no overlap with last working year)

    end_mode:
      "specific"    → use stored end_age
      "retirement"  → retirement_age      (last working year)
      "death"       → death_age
    """
    resolved = []
    for ev in events:
        ev = dict(ev)

        # Support legacy boolean flags from older session-state data
        start_mode = ev.get("start_mode") or ("retirement" if ev.get("start_is_retirement") else "specific")
        end_mode   = ev.get("end_mode")   or ("retirement" if ev.get("end_is_retirement")   else "specific")

        if start_mode == "retirement":
            ev["start_age"] = retirement_age + 1
        if end_mode == "retirement":
            ev["end_age"] = retirement_age
        elif end_mode == "death":
            ev["end_age"] = death_age

        resolved.append(ev)
    return resolved


# ── Legacy DataFrame helpers ───────────────────────────────────────────────────

_COLS = ["name", "type", "monthly_amount", "start_age", "end_age", "annual_rate", "notes"]


def events_to_df(events):
    if not events:
        return pd.DataFrame(columns=_COLS)
    df = pd.DataFrame(events)[_COLS].copy()
    df["monthly_amount"] = df["monthly_amount"].astype(float)
    df["start_age"]      = df["start_age"].astype("Int64")
    df["end_age"]        = df["end_age"].astype("Int64")
    df["annual_rate"]    = df["annual_rate"].astype(float)
    df["notes"]          = df["notes"].fillna("").astype(str)
    return df


def df_to_events(df):
    events = []
    for _, row in df.iterrows():
        name = row.get("name")
        if pd.isna(name) or str(name).strip() == "":
            continue
        monthly = row.get("monthly_amount")
        sa = row.get("start_age")
        ea = row.get("end_age")
        if pd.isna(monthly) or pd.isna(sa) or pd.isna(ea):
            continue
        type_ = row.get("type")
        rate  = row.get("annual_rate", 0.0)
        notes = row.get("notes", "")
        events.append({
            "name":           str(name).strip(),
            "type":           str(type_) if not pd.isna(type_) else "expense",
            "monthly_amount": float(monthly),
            "start_age":      int(sa),
            "end_age":        int(ea),
            "start_mode":     "specific",
            "end_mode":       "specific",
            "annual_rate":    float(rate) if not pd.isna(rate) else 0.0,
            "notes":          str(notes) if not pd.isna(notes) else "",
        })
    return events
