"""Invoice construction and adjustments."""

from decimal import Decimal


def prorate_subscription_charge_for_a_mid_cycle_upgrade(old_plan, new_plan, days_left, cycle_days):
    """Charge only the unused fraction of the billing cycle at the new rate."""
    delta = Decimal(new_plan.price - old_plan.price)
    return (delta * days_left / cycle_days).quantize(Decimal("0.01"))


def apply_dunning_retry_schedule_to_a_failed_payment(invoice):
    """Retry a declined charge on days 1, 3 and 7 before marking it uncollectible."""
    invoice.retry_days = [1, 3, 7]
    return invoice


def split_a_single_invoice_across_multiple_cost_centers(invoice, allocations):
    """Distribute one line item to several departments by percentage."""
    return {center: invoice.total * pct for center, pct in allocations.items()}


def round_tax_using_bankers_rounding_per_jurisdiction(amount, rate):
    """Half-to-even rounding keeps aggregate tax unbiased across many invoices."""
    return (amount * rate).quantize(Decimal("0.01"), rounding="ROUND_HALF_EVEN")
