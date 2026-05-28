import numpy as np

from calculator import EARLY_WITHDRAWAL_CUTOFF


def run_monte_carlo(
    events, brokerage_balance, retirement_balance, retirement_age,
    return_pre, return_post, early_withdrawal_rate,
    current_age, death_age,
    n_sims,
    return_pre_std,   # as fraction, e.g. 0.10 for ±10%
    return_post_std,
    return_floor,     # hard minimum annual return, e.g. -0.50
    event_stds,       # {event_name: std_dev in percentage points, e.g. 1.0 for ±1%/yr}
):
    """
    Run n_sims Monte Carlo simulations.

    Portfolio returns are sampled independently each year from a normal
    distribution. Event rates are sampled once per simulation (persistent
    over the full horizon — models "what if inflation runs hot for decades"
    rather than random year-to-year noise).

    Returns ages, per-age percentile bands, success rate, and final balances.
    """
    ages = list(range(current_age, death_age + 1))
    n_ages = len(ages)
    rng = np.random.default_rng()

    # Pre-sample all portfolio returns upfront — shape (n_sims, n_ages)
    pre_samples = np.clip(
        rng.normal(return_pre, return_pre_std, (n_sims, n_ages)) if return_pre_std > 0
        else np.full((n_sims, n_ages), return_pre),
        return_floor, None,
    )
    post_samples = np.clip(
        rng.normal(return_post, return_post_std, (n_sims, n_ages)) if return_post_std > 0
        else np.full((n_sims, n_ages), return_post),
        return_floor, None,
    )

    # Pre-sample event rates once per simulation — shape (n_sims,) per event
    ev_rate_samples = {}
    for ev in events:
        name = ev["name"]
        std = event_stds.get(name, 0.0)
        ev_rate_samples[name] = (
            rng.normal(ev["annual_rate"], std, n_sims) if std > 0
            else np.full(n_sims, ev["annual_rate"])
        )

    use_post = [age >= retirement_age for age in ages]
    all_totals = np.zeros((n_sims, n_ages))
    successes = 0

    for sim in range(n_sims):
        curr_brokerage = float(brokerage_balance)
        curr_retirement = float(retirement_balance)
        depleted = False

        for yi, age in enumerate(ages):
            all_totals[sim, yi] = curr_brokerage + curr_retirement

            annual_income = annual_expenses = annual_ret_contrib = annual_brk_contrib = 0.0
            for ev in events:
                if ev["start_age"] <= age <= ev["end_age"]:
                    yrs = age - ev["start_age"]
                    rate = float(ev_rate_samples[ev["name"]][sim])
                    amt = ev["monthly_amount"] * 12 * ((1 + rate / 100) ** yrs)
                    t = ev["type"]
                    if t == "income":
                        annual_income += amt
                    elif t == "expense":
                        annual_expenses += amt
                    elif t == "retirement_contribution":
                        annual_ret_contrib += amt
                    elif t == "brokerage_contribution":
                        annual_brk_contrib += amt

            net_budget = annual_income - annual_expenses - annual_ret_contrib - annual_brk_contrib

            r = post_samples[sim, yi] if use_post[yi] else pre_samples[sim, yi]
            curr_brokerage = curr_brokerage * (1 + r) + annual_brk_contrib
            curr_retirement = curr_retirement * (1 + r) + annual_ret_contrib

            if net_budget >= 0:
                curr_brokerage += net_budget
            else:
                need = -net_budget
                if curr_brokerage >= need:
                    curr_brokerage -= need
                else:
                    from_ret = need - curr_brokerage
                    curr_brokerage = 0.0
                    if age < EARLY_WITHDRAWAL_CUTOFF and early_withdrawal_rate > 0:
                        from_ret = from_ret / (1 - early_withdrawal_rate)
                    curr_retirement -= from_ret

            curr_retirement = max(0.0, curr_retirement)
            curr_brokerage = max(0.0, curr_brokerage)

            if curr_brokerage + curr_retirement <= 0 and age < death_age:
                depleted = True

        if not depleted:
            successes += 1

    return {
        "ages": ages,
        "percentiles": {p: np.percentile(all_totals, p, axis=0).tolist() for p in [10, 25, 50, 75, 90]},
        "success_rate": successes / n_sims,
        "final_totals": all_totals[:, -1].tolist(),
    }
