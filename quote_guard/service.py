"""The checker itself, independent of MCP so it can be tested and reused."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from .core import Token, Verdict, assess, rank, to_decimal
from .parse import parse_quote
from .prices import Fetcher, _http_get, usd_price


def token_from_dict(d: dict[str, Any]) -> Token:
    return Token(
        symbol=str(d.get("symbol", "?")),
        decimals=int(d["decimals"]),
        network=str(d.get("network") or d.get("networkId") or ""),
        contract_address=str(d.get("contractAddress", "0") or "0"),
    )


def check_swap_quotes(
    from_token: dict[str, Any],
    to_token: dict[str, Any],
    quotes: list[dict[str, Any]],
    max_cost_bps: float = 50,
    price_from_usd: Optional[float] = None,
    price_to_usd: Optional[float] = None,
    from_amount_minor: Optional[str] = None,
    fetch: Fetcher = _http_get,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    ft, tt = token_from_dict(from_token), token_from_dict(to_token)

    p_from = to_decimal(price_from_usd) if price_from_usd is not None else usd_price(ft, fetch)
    p_to = to_decimal(price_to_usd) if price_to_usd is not None else usd_price(tt, fetch)
    if not p_from or not p_to:
        missing = [t.symbol for t, p in ((ft, p_from), (tt, p_to)) if not p]
        return {
            "recommendation": None,
            "action": "STOP",
            "message": f"No reference price for {', '.join(missing)}. Ask the user for a "
                       f"USD price, or pass price_from_usd / price_to_usd.",
            "assessments": [],
        }

    assessments, errors = [], []
    for q in quotes:
        provider = str(q.get("provider", "unknown"))
        try:
            quote = parse_quote(q.get("response", q), provider, ft, tt,
                                rate_type=str(q.get("rateType", "float")),
                                from_amount_minor=from_amount_minor,
                                fee_usd=q.get("fee_usd"))
            assessments.append(assess(quote, p_from, p_to, Decimal(str(max_cost_bps)), now))
        except (ValueError, KeyError, ArithmeticError) as e:
            errors.append({"provider": provider, "error": str(e)})

    ranked = rank(assessments)
    best = ranked[0] if ranked else None

    if best is None:
        action, msg = "STOP", "No quote could be read."
    elif best.verdict is Verdict.PASS:
        action = "OK_TO_CREATE_INTENT"
        msg = (f"Best quote: {best.provider}, cost {best.cost_bps:.1f} bps vs reference. "
               f"Show this to the user; if they agree, call express__exchange_intent_create "
               f"once with provider={best.provider!r} (do not retry on error).")
    elif best.verdict is Verdict.WARN:
        action = "ASK_USER"
        msg = (f"Best quote ({best.provider}) costs {best.cost_bps:.1f} bps, above the "
               f"{max_cost_bps} bps tolerance. Only create an intent if the user explicitly "
               f"accepts this cost.")
    elif best.verdict is Verdict.STALE:
        action, msg = "REQUOTE", "All usable quotes have expired. Fetch fresh quotes."
    else:
        action = "DO_NOT_SWAP"
        msg = (f"Every quote failed the check (best: {best.provider}, "
               f"{best.verdict.value}). Do not create an intent; tell the user why.")

    return {
        "recommendation": best.provider if best and best.verdict in (Verdict.PASS, Verdict.WARN) else None,
        "action": action,
        "message": msg,
        "reference": {
            f"{ft.symbol}_usd": float(p_from),
            f"{tt.symbol}_usd": float(p_to),
            "max_cost_bps": max_cost_bps,
        },
        "assessments": [a.to_dict() for a in ranked],
        "errors": errors,
    }
