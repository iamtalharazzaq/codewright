"""Money formatting for the reports (amounts are kept in cents)."""

CURRENCY_SYMBOLS = {"EUR": "€", "GBP": "£", "USD": "$"}


def format_cents(cents: int, currency: str = "EUR") -> str:
    """1234 → '€12.34'; negative amounts get a leading minus."""
    sign = "-" if cents < 0 else ""
    whole, rest = divmod(abs(cents), 100)
    symbol = CURRENCY_SYMBOLS.get(currency, currency + " ")
    return f"{sign}{symbol}{whole:,}.{rest:02d}"


def split_evenly(cents: int, parts: int) -> list[int]:
    """Split an amount into `parts` shares that differ by at most one cent and add up to the amount."""
    if parts <= 0:
        raise ValueError("parts must be positive")
    base, extra = divmod(cents, parts)
    return [base + (1 if i < extra else 0) for i in range(parts)]
