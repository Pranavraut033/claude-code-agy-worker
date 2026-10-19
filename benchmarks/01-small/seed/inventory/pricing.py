"""Pricing: line totals, order totals and volume discounts.

Money is computed in Decimal and rounded half-up to cents, so totals match
what a person adding them on paper would get.
"""

from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")

# (threshold, rate): an order total at or above the threshold gets the rate.
DISCOUNT_TIERS = [(1000, Decimal("0.15")), (500, Decimal("0.10")), (100, Decimal("0.05"))]


def _money(value):
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def line_total(item):
    """unit_price * qty for one item, rounded to cents."""
    return _money(Decimal(str(item.unit_price)) * item.qty)


def calc_total(items):
    """Sum of line totals for ``items``, as a float rounded to cents."""
    return float(sum((line_total(i) for i in items), Decimal("0")))


def discount_rate(total):
    """Discount rate for an order total: 15% from 1000, 10% from 500, 5% from 100."""
    for threshold, rate in DISCOUNT_TIERS:
        if total >= threshold:
            return rate
    return Decimal("0")


def discounted_total(items):
    """calc_total minus the volume discount, rounded to cents."""
    total = Decimal(str(calc_total(items)))
    return float(_money(total * (1 - discount_rate(total))))
