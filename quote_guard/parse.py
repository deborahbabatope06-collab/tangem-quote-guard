"""Tolerant parser for `express__exchange_quote` responses.

Tangem's docs list what the quote contains (amounts, min/max, fees, txType,
expiredAt) but not the exact field names for amounts, min/max or fees. So
instead of hard-coding one schema, we flatten the response and look for keys
by pattern. If the real response uses different names, add them to the
patterns below; `explain_fields()` shows what was found where.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from .core import Quote, Token, to_decimal

# Patterns are matched against the full dotted path, case-insensitively.
TO_AMOUNT = [r"(^|\.)to\.amount$", r"(^|\.)to_?amount$", r"(^|\.)amount_?to$", r"(^|\.)amount_?out$"]
FROM_AMOUNT = [r"(^|\.)from\.amount$", r"(^|\.)from_?amount$", r"(^|\.)amount_?from$", r"(^|\.)amount_?in$"]
MIN_AMOUNT = [r"(^|\.)min_?amount$", r"(^|\.)from\.min$", r"(^|\.)min$", r"(^|\.)from_?amount\.min$"]
MAX_AMOUNT = [r"(^|\.)max_?amount$", r"(^|\.)from\.max$", r"(^|\.)max$", r"(^|\.)from_?amount\.max$"]
EXPIRY = [r"(^|\.)expired_?at$", r"(^|\.)expires_?at$", r"(^|\.)expiry$"]
FEE_USD = [r"fee.*usd", r"usd.*fee"]


def flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(flatten(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = obj
    return out


def _find(flat: dict[str, Any], patterns: list[str]) -> tuple[Optional[str], Any]:
    for pat in patterns:
        rx = re.compile(pat, re.IGNORECASE)
        for path, val in flat.items():
            if rx.search(path) and val is not None:
                return path, val
    return None, None


def _parse_time(v: Any) -> Optional[datetime]:
    if v is None:
        return None
    if isinstance(v, (int, float)) or (isinstance(v, str) and v.isdigit()):
        ts = float(v)
        if ts > 1e12:  # milliseconds
            ts /= 1000
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def load(raw: Any) -> dict[str, Any]:
    """Accept a dict, a JSON string, or an MCP tool result with text content."""
    if isinstance(raw, str):
        return json.loads(raw)
    if isinstance(raw, dict) and "content" in raw and isinstance(raw["content"], list):
        for block in raw["content"]:
            if isinstance(block, dict) and block.get("type") == "text":
                try:
                    return json.loads(block["text"])
                except (json.JSONDecodeError, KeyError):
                    continue
        if isinstance(raw.get("structuredContent"), dict):
            return raw["structuredContent"]
    if isinstance(raw, dict):
        return raw
    raise ValueError("Quote must be a dict or a JSON string.")


def parse_quote(
    raw: Any,
    provider: str,
    from_token: Token,
    to_token: Token,
    rate_type: str = "float",
    from_amount_minor: Optional[Any] = None,
    fee_usd: Optional[Any] = None,
) -> Quote:
    """Build a Quote. `from_amount_minor` is the amount you requested; it is used
    if the response doesn't echo it back."""
    data = load(raw)
    flat = flatten(data)

    _, to_amt = _find(flat, TO_AMOUNT)
    _, from_amt = _find(flat, FROM_AMOUNT)
    _, mn = _find(flat, MIN_AMOUNT)
    _, mx = _find(flat, MAX_AMOUNT)
    _, exp = _find(flat, EXPIRY)
    if fee_usd is None:
        _, fee_usd = _find(flat, FEE_USD)

    from_val = to_decimal(from_amt) if from_amt is not None else to_decimal(from_amount_minor)
    to_val = to_decimal(to_amt)
    if from_val is None or to_val is None:
        raise ValueError(
            "Could not find from/to amounts in the quote. Fields seen: "
            + ", ".join(sorted(flat)[:40])
        )

    return Quote(
        provider=provider,
        from_token=from_token,
        to_token=to_token,
        from_amount_minor=from_val,
        to_amount_minor=to_val,
        rate_type=rate_type,
        fee_usd=to_decimal(fee_usd) or Decimal(0),
        min_from_minor=to_decimal(mn),
        max_from_minor=to_decimal(mx),
        expires_at=_parse_time(exp),
        raw=data,
    )


def explain_fields(raw: Any) -> dict[str, Optional[str]]:
    """Debug helper: which response path was used for each field."""
    flat = flatten(load(raw))
    return {
        "to_amount": _find(flat, TO_AMOUNT)[0],
        "from_amount": _find(flat, FROM_AMOUNT)[0],
        "min": _find(flat, MIN_AMOUNT)[0],
        "max": _find(flat, MAX_AMOUNT)[0],
        "expiry": _find(flat, EXPIRY)[0],
        "fee_usd": _find(flat, FEE_USD)[0],
    }
