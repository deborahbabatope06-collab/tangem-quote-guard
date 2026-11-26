"""Core maths: turn a Tangem Express quote into an execution-cost verdict.

All amounts are handled as Decimal. Tangem quotes amounts in minor units
(e.g. wei for ETH, 1e-6 for USDC), so every amount is scaled by the
token's `decimals` before any pricing.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Optional

BPS = Decimal(10_000)


class Verdict(str, Enum):
    PASS = "PASS"      # cost within tolerance: OK to create the intent
    WARN = "WARN"      # cost above tolerance but under 2x: ask the user explicitly
    BLOCK = "BLOCK"    # cost too high: do not create the intent
    STALE = "STALE"    # quote already expired: re-quote first
    INVALID = "INVALID"  # quote could not be read or amount out of bounds


@dataclass(frozen=True)
class Token:
    symbol: str
    decimals: int
    network: str = ""
    contract_address: str = "0"  # "0" = native coin, as in Tangem's API

    def to_units(self, minor: Decimal | int | str) -> Decimal:
        """Minor units -> whole tokens."""
        return Decimal(str(minor)) / (Decimal(10) ** self.decimals)


@dataclass
class Quote:
    provider: str
    from_token: Token
    to_token: Token
    from_amount_minor: Decimal
    to_amount_minor: Decimal
    rate_type: str = "float"
    fee_usd: Decimal = Decimal(0)          # any fee charged on top of the swap
    min_from_minor: Optional[Decimal] = None
    max_from_minor: Optional[Decimal] = None
    expires_at: Optional[datetime] = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def from_amount(self) -> Decimal:
        return self.from_token.to_units(self.from_amount_minor)

    @property
    def to_amount(self) -> Decimal:
        return self.to_token.to_units(self.to_amount_minor)

    @property
    def rate(self) -> Decimal:
        """Units of `to` received per unit of `from`."""
        return self.to_amount / self.from_amount


@dataclass
class Assessment:
    provider: str
    verdict: Verdict
    cost_bps: Optional[Decimal]
    rate: Optional[Decimal]
    reference_rate: Optional[Decimal]
    value_in_usd: Optional[Decimal]
    value_out_usd: Optional[Decimal]
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["verdict"] = self.verdict.value
        for k in ("cost_bps", "rate", "reference_rate", "value_in_usd", "value_out_usd"):
            if d[k] is not None:
                d[k] = float(round(d[k], 6))
        return d


def assess(
    quote: Quote,
    price_from_usd: Decimal,
    price_to_usd: Decimal,
    max_cost_bps: Decimal = Decimal(50),
    now: Optional[datetime] = None,
) -> Assessment:
    """Score one quote against reference USD prices.

    cost_bps = (1 - (V_out - fee) / V_in) * 10_000, where V = amount x price.
    Positive cost = you lose value vs the reference mid; negative = better than mid.
    """
    now = now or datetime.now(timezone.utc)
    reasons: list[str] = []

    if quote.from_amount_minor <= 0 or quote.to_amount_minor <= 0:
        return Assessment(quote.provider, Verdict.INVALID, None, None, None, None, None,
                          ["Quote has a zero or negative amount."])
    if price_from_usd <= 0 or price_to_usd <= 0:
        return Assessment(quote.provider, Verdict.INVALID, None, None, None, None, None,
                          ["Missing or non-positive reference price."])

    if quote.min_from_minor is not None and quote.from_amount_minor < quote.min_from_minor:
        reasons.append(f"Amount is below the provider minimum "
                       f"({quote.from_token.to_units(quote.min_from_minor)} {quote.from_token.symbol}).")
        verdict_override = Verdict.INVALID
    elif quote.max_from_minor is not None and quote.from_amount_minor > quote.max_from_minor:
        reasons.append(f"Amount is above the provider maximum "
                       f"({quote.from_token.to_units(quote.max_from_minor)} {quote.from_token.symbol}).")
        verdict_override = Verdict.INVALID
    else:
        verdict_override = None

    value_in = quote.from_amount * price_from_usd
    value_out = quote.to_amount * price_to_usd - quote.fee_usd
    cost_bps = (Decimal(1) - value_out / value_in) * BPS
    reference_rate = price_from_usd / price_to_usd

    if quote.expires_at is not None and quote.expires_at <= now:
        reasons.append("Quote has expired; request a new one before creating an intent.")
        verdict = Verdict.STALE
    elif verdict_override is not None:
        verdict = verdict_override
    elif cost_bps <= max_cost_bps:
        verdict = Verdict.PASS
        reasons.append(f"Cost {cost_bps:.1f} bps is within the {max_cost_bps} bps tolerance.")
    elif cost_bps <= 2 * max_cost_bps:
        verdict = Verdict.WARN
        reasons.append(f"Cost {cost_bps:.1f} bps is above the {max_cost_bps} bps tolerance; "
                       f"confirm with the user before proceeding.")
    else:
        verdict = Verdict.BLOCK
        reasons.append(f"Cost {cost_bps:.1f} bps is more than double the "
                       f"{max_cost_bps} bps tolerance; do not create an intent.")

    if cost_bps < Decimal(-100):
        reasons.append("Quote is more than 1% better than the reference price, which is "
                       "unusual: check the reference price and token decimals.")

    return Assessment(quote.provider, verdict, cost_bps, quote.rate, reference_rate,
                      value_in, value_out, reasons)


_ORDER = {Verdict.PASS: 0, Verdict.WARN: 1, Verdict.BLOCK: 2, Verdict.STALE: 3, Verdict.INVALID: 4}


def rank(assessments: list[Assessment]) -> list[Assessment]:
    """Best first: usable verdicts first, then lowest cost."""
    def key(a: Assessment):
        return (_ORDER[a.verdict], a.cost_bps if a.cost_bps is not None else Decimal("Infinity"))
    return sorted(assessments, key=key)


def to_decimal(x: Any) -> Optional[Decimal]:
    if x is None or isinstance(x, bool):
        return None
    try:
        return Decimal(str(x))
    except (InvalidOperation, ValueError):
        return None
