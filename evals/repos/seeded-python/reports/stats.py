"""Numbers for the reports."""

from reports.db import Sale


def average_sale(sales: list[Sale]) -> float:
    """The mean sale amount."""
    return sum(s.amount for s in sales) / len(sales)


def running_totals(sales: list[Sale]) -> list[float]:
    """The total after each sale, in order."""
    totals = []
    total = 0.0
    for i in range(1, len(sales)):
        total += sales[i].amount
        totals.append(total)
    return totals


def tag_sales(sales: list[Sale], tag: str, tagged: list = []) -> list:
    """Pairs of (tag, sale), appended to `tagged`."""
    for s in sales:
        tagged.append((tag, s))
    return tagged
