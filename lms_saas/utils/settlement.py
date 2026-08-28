"""Settlement helpers (R53-T9 / #61) — early-settlement rebate math.

The method locked in #53: **Rule of 78** (sum-of-digits) for flat-rate
loans. Reducing-balance loans have no rebate — Lending's
``calculate_amounts(payment_type="Full Settlement")`` already charges
accrued interest only, so unearned future interest is never collected.

Rule of 78: for a loan of N periods, the digit weights are N, N-1, ..., 1
(summing to N(N+1)/2). After k instalments the earned interest is
(sum of the k largest digits / total) x total_interest, so the rebate is:

    rebate = total_interest x (remaining digits sum / total digits sum)
           = total_interest x ((N-k)(N-k+1)/2) / (N(N+1)/2)
"""

from __future__ import annotations

from typing import Literal

from frappe.utils import flt, rounded

SettlementMethod = Literal["Rule of 78", "None"]


def rule_of_78_rebate(
    *, total_interest: float, periods: int, instalments_paid: int
) -> float:
    """Rebate under the Rule of 78 (sum-of-digits) method.

    Args:
        total_interest: Total contracted interest over the full term.
        periods: Number of scheduled instalments (tenure).
        instalments_paid: How many instalments the borrower has paid when
            settling early.

    Returns:
        The rebate, rounded to 2dp. Zero when nothing has been settled
        early (0 instalments paid or the full term already paid).
    """
    if periods <= 0 or instalments_paid <= 0 or instalments_paid >= periods:
        return 0.0
    remaining = periods - instalments_paid
    remaining_digits = remaining * (remaining + 1) / 2
    total_digits = periods * (periods + 1) / 2
    rebate = total_interest * remaining_digits / total_digits
    return rounded(rebate, 2)


def settlement_method_for(schedule_type: str) -> SettlementMethod:
    """Which rebate method applies for this loan product's schedule type."""
    return "Rule of 78" if schedule_type == "Flat Interest Rate" else "None"