import pandas as pd

CURRENT_AGE = 40
DEATH_AGE = 95

# Penalty-free retirement withdrawal threshold (59½ rule, approximated annually)
EARLY_WITHDRAWAL_CUTOFF = 60


def calculate_fire(events, brokerage_balance, retirement_balance, retirement_age,
                   return_pre, return_post, early_withdrawal_rate=0.35,
                   current_age=None, death_age=None):
    """
    Simulate net worth year-by-year given a list of financial events.

    Budget model (unified for all ages):
        net_budget = income − expenses − retirement_contributions − brokerage_contributions

        Positive net_budget → surplus credited to brokerage.
        Negative net_budget → deficit drawn first from brokerage, then retirement.

    Contribution events simultaneously reduce the budget and directly credit their target account,
    modelling that 401k/brokerage contributions are paid from income.

    Draw order post-brokerage exhaustion:
        Brokerage → 0 first, then retirement.
        Before age 60 (59½ rule): retirement withdrawals are grossed up so the account
        loses  net_needed / (1 − early_withdrawal_rate)  while you only receive net_needed.
        e.g. early_withdrawal_rate=0.35 → 10% IRS penalty + ~25% income tax.

    Annual rate compounds each event's monthly amount:
        annual_amount = monthly * 12 * (1 + rate%/100) ^ years_since_start
    """
    current_age = current_age if current_age is not None else CURRENT_AGE
    death_age   = death_age   if death_age   is not None else DEATH_AGE

    curr_brokerage = float(brokerage_balance)
    curr_retirement = float(retirement_balance)
    success = True
    rows = []

    for age in range(current_age, death_age + 1):
        total_nw = curr_brokerage + curr_retirement

        # --- Aggregate active events ---
        annual_income = 0.0
        annual_expenses = 0.0
        annual_ret_contrib = 0.0
        annual_brk_contrib = 0.0

        for ev in events:
            if ev["start_age"] <= age <= ev["end_age"]:
                yrs = age - ev["start_age"]
                amt = ev["monthly_amount"] * 12 * ((1 + ev["annual_rate"] / 100) ** yrs)
                t = ev["type"]
                if t == "income":
                    annual_income += amt
                elif t == "expense":
                    annual_expenses += amt
                elif t == "retirement_contribution":
                    annual_ret_contrib += amt
                elif t == "brokerage_contribution":
                    annual_brk_contrib += amt

        # Net budget: income minus ALL outflows (expenses + both contribution types).
        # Contributions come from income — negative budget means drawing from savings.
        net_budget = annual_income - annual_expenses - annual_ret_contrib - annual_brk_contrib

        # --- Pre-compute penalty for this year (using post-growth brokerage) ---
        # Growth is applied first, then contributions, then the budget deficit is covered.
        rate = return_pre if age < retirement_age else return_post
        post_brk = curr_brokerage * (1 + rate) + annual_brk_contrib
        post_ret = curr_retirement * (1 + rate) + annual_ret_contrib

        annual_penalty = 0.0
        if net_budget < 0:
            need = -net_budget
            if post_brk < need:                          # brokerage won't cover it
                from_ret = need - post_brk
                if age < EARLY_WITHDRAWAL_CUTOFF and early_withdrawal_rate > 0:
                    gross = from_ret / (1 - early_withdrawal_rate)
                    annual_penalty = gross - from_ret    # penalty + tax lost

        rows.append({
            "Age": age,
            "Brokerage": curr_brokerage,
            "Retirement": curr_retirement,
            "Total": total_nw,
            "Mo Income": annual_income / 12,
            "Mo Expenses": annual_expenses / 12,
            "Mo Ret Contrib": annual_ret_contrib / 12,
            "Mo Brk Contrib": annual_brk_contrib / 12,
            "Mo Net Budget": net_budget / 12,            # + surplus  / − deficit
            "Mo Penalty": annual_penalty / 12,           # cost of early withdrawal
        })

        # --- Commit growth and contributions ---
        curr_brokerage = post_brk
        curr_retirement = post_ret

        # --- Apply net budget surplus / deficit ---
        if net_budget >= 0:
            curr_brokerage += net_budget
        else:
            need = -net_budget
            if curr_brokerage >= need:
                curr_brokerage -= need
            else:
                # Brokerage exhausted → draw remainder from retirement
                from_ret = need - curr_brokerage
                curr_brokerage = 0.0
                if age < EARLY_WITHDRAWAL_CUTOFF and early_withdrawal_rate > 0:
                    # Gross up: account loses more than we net to cover penalty + tax
                    gross = from_ret / (1 - early_withdrawal_rate)
                else:
                    gross = from_ret
                curr_retirement -= gross

        curr_retirement = max(0.0, curr_retirement)
        curr_brokerage = max(0.0, curr_brokerage)

        if (curr_brokerage + curr_retirement) <= 0 and age < death_age:
            success = False

    return {
        "df": pd.DataFrame(rows),
        "success": success,
        "final_amount": rows[-1]["Total"] if rows else 0.0,
    }
