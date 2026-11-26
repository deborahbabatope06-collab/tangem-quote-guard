"""MCP server exposing the quote checker to an AI client that also has
Tangem's MCP server connected.

Run:  python -m quote_guard.server            (stdio, for Claude Desktop / Code)
"""

from __future__ import annotations

from typing import Any, Optional

try:  # MCP Python SDK v2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # SDK v1
    from mcp.server.fastmcp import FastMCP as _Server

from .parse import explain_fields
from .service import check_swap_quotes as _check

INSTRUCTIONS = """\
Quote Guard checks Tangem Express swap quotes against a market reference price
before any swap request is created. Workflow for any swap the user asks for:
1. Use Tangem's express__pairs to find the providers and rate types for the pair.
2. Call Tangem's express__exchange_quote once per provider, same amount each time.
3. Pass every quote to check_swap_quotes (include the token's network,
   contractAddress, decimals and symbol).
4. Follow the returned `action`: only call express__exchange_intent_create when it
   is OK_TO_CREATE_INTENT (or ASK_USER and the user explicitly accepts the cost),
   using the recommended provider. Never retry intent creation after an error.
5. Show the user the cost in basis points and the signing deeplink.
"""

mcp = _Server("tangem-quote-guard", instructions=INSTRUCTIONS)


@mcp.tool()
def check_swap_quotes(
    from_token: dict[str, Any],
    to_token: dict[str, Any],
    quotes: list[dict[str, Any]],
    max_cost_bps: float = 50,
    price_from_usd: Optional[float] = None,
    price_to_usd: Optional[float] = None,
    from_amount_minor: Optional[str] = None,
) -> dict[str, Any]:
    """Rank Tangem Express quotes by execution cost against a reference price.

    from_token / to_token: {"symbol", "network", "contractAddress" ("0" for native), "decimals"}.
    quotes: list of {"provider", "rateType", "response": <raw express__exchange_quote result>}.
    max_cost_bps: tolerated cost vs reference mid, in basis points (50 = 0.5%).
    price_*_usd: optional manual reference prices; fetched from CoinGecko if omitted.
    from_amount_minor: the amount you quoted, in minor units, if the response omits it.

    Returns a recommended provider, an `action` to follow, and per-quote assessments.
    """
    return _check(from_token, to_token, quotes, max_cost_bps,
                  price_from_usd, price_to_usd, from_amount_minor)


@mcp.tool()
def explain_quote_fields(response: dict[str, Any]) -> dict[str, Any]:
    """Debug: show which fields of a raw express__exchange_quote response were read
    as the from/to amounts, min/max, expiry and fee."""
    return explain_fields(response)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
