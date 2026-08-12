"""Pure loan calculation helpers.

Centralised, side-effect-free functions used by dashboards, portal APIs,
reports and the nightly cron. Keeping them pure makes them unit-testable
without a database and guarantees consistent figures across the system.
"""

from frappe.utils import flt

# Delinquency thresholds (days past due)
WATCHLIST_DPD = 30
NPA_DPD = 90


def principal_outstanding(loan_amount, total_principal_paid=0, written_off_amount=0):
    """Outstanding principal exposure (never negative). Used for portfolio/PAR."""
    return max(flt(loan_amount) - flt(total_principal_paid) - flt(written_off_amount), 0)


def remaining_payable(total_payment, total_amount_paid=0):
    """Borrower-facing balance owed = total payable (principal+interest) minus paid."""
    return max(flt(total_payment) - flt(total_amount_paid), 0)


def asset_classification(dpd):
    """Prudential asset classification from days past due."""
    dpd = flt(dpd)
    if dpd > NPA_DPD:
        return "Non-Performing Asset (NPA)"
    if dpd > WATCHLIST_DPD:
        return "Sub-Standard/Watchlist"
    return None


def par_bucket(dpd):
    """PAR aging bucket label (PAR1/30/60/90 convention)."""
    dpd = flt(dpd)
    if dpd <= 0:
        return "0 - Current"
    if dpd <= 30:
        return "1-30 Days"
    if dpd <= 60:
        return "31-60 Days"
    if dpd <= 90:
        return "61-90 Days"
    return "90+ Days"


def ecl_stage(dpd):
    """IFRS 9 expected-credit-loss staging from days past due.

    Stage 1: performing (<=30 DPD), Stage 2: significant increase in credit
    risk (31-90 DPD), Stage 3: credit-impaired / default (>90 DPD).
    """
    dpd = flt(dpd)
    if dpd > NPA_DPD:
        return 3
    if dpd > WATCHLIST_DPD:
        return 2
    return 1


# IFRS 9 simplified provision matrix (ECL coverage rate per stage/bucket).
# Calibrated placeholder rates; institutions tune from historical loss data.
ECL_PROVISION_RATES = {1: 0.01, 2: 0.10, 3: 0.50}


def expected_credit_loss(exposure, dpd):
    """Provision amount = exposure * stage coverage rate (provision matrix)."""
    rate = ECL_PROVISION_RATES.get(ecl_stage(dpd), 0)
    return flt(exposure) * rate


# ---------------------------------------------------------------------------
# Amortization helpers (R01 — release-gate 1.2 / 1.3 / 1.4)
#
# Pure-Python mirror of lms_saas.api.portal.get_loan_estimate. Keeping the
# math in a side-effect-free helper means we can pin the rounding invariant
# (1.3) and the day-count boundaries (1.4) in unit tests without standing
# up a Loan Product fixture or a customer context.
# ---------------------------------------------------------------------------


def amortize(
    principal,
    annual_rate_pct,
    periods,
    *,
    day_count_convention="actual/365",
    period_start=None,
):
    """Constant-payment amortization for ``periods`` monthly periods.

    Returns a dict with ``monthly_payment``, ``total_payable``,
    ``total_interest``, and the day-count convention used. Behaviour
    mirrors the portal estimator so the wrapper and the math stay in
    lock-step.

    Day-count convention only affects the *displayed* first-period
    interest accrual when ``period_start`` is supplied; the monthly
    payment itself is unchanged because the upstream lending engine
    charges a constant monthly instalment.
    """
    from math import pow

    if periods <= 0:
        raise ValueError("periods must be positive")
    if principal <= 0:
        raise ValueError("principal must be positive")

    monthly_rate = flt(annual_rate_pct) / 100 / 12
    if monthly_rate > 0:
        monthly_payment = flt(principal) * monthly_rate / (
            1 - pow(1 + monthly_rate, -periods)
        )
    else:
        monthly_payment = flt(principal) / periods

    total_payable = monthly_payment * periods
    total_interest = total_payable - flt(principal)

    return {
        "monthly_payment": flt(monthly_payment),
        "total_payable": flt(total_payable),
        "total_interest": flt(total_interest),
        "rate_of_interest": flt(annual_rate_pct),
        "principal": flt(principal),
        "periods": int(periods),
        "day_count_convention": day_count_convention,
        "period_start": period_start,
    }
