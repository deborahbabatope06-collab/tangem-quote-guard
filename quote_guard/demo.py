"""Offline demo: 1 ETH -> USDC on Ethereum, three made-up providers.

The responses below are MOCK data shaped like express__exchange_quote output
(field names are a guess, since Tangem's docs don't publish them). Prices are fixed so the
demo runs with no network.   Run:  python -m quote_guard.demo
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .service import check_swap_quotes

ETH = {"symbol": "ETH", "network": "ethereum", "contractAddress": "0", "decimals": 18}
USDC = {"symbol": "USDC", "network": "ethereum",
        "contractAddress": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", "decimals": 6}

ONE_ETH = str(10**18)
SOON = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
GONE = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()

MOCK_QUOTES = [
    {"provider": "provider_a", "rateType": "float",
     "response": {"from": {"amount": ONE_ETH}, "to": {"amount": "2988500000"},   # 2988.50 USDC
                  "minAmount": str(10**16), "expiredAt": SOON, "txType": "send"}},
    {"provider": "provider_b", "rateType": "fixed",
     "response": {"from": {"amount": ONE_ETH}, "to": {"amount": "2955000000"},   # 2955.00 USDC
                  "expiredAt": SOON, "txType": "swap"}},
    {"provider": "provider_c", "rateType": "float",
     "response": {"from": {"amount": ONE_ETH}, "to": {"amount": "2999000000"},   # best rate, but expired
                  "expiredAt": GONE, "txType": "send"}},
    {"provider": "provider_d", "rateType": "float",
     "response": {"from": {"amount": ONE_ETH}, "to": {"amount": "2820000000"},   # 2820.00 USDC
                  "expiredAt": SOON, "txType": "send"}},
]


def main() -> None:
    result = check_swap_quotes(ETH, USDC, MOCK_QUOTES, max_cost_bps=50,
                               price_from_usd=3000.0, price_to_usd=1.0)
    print("Swap 1 ETH -> USDC   reference: ETH $3000.00, USDC $1.00, tolerance 50 bps\n")
    print(f"{'provider':<12}{'verdict':<9}{'rate':>10}{'cost (bps)':>12}")
    print("-" * 43)
    for a in result["assessments"]:
        rate = f"{a['rate']:.2f}" if a["rate"] is not None else "-"
        cost = f"{a['cost_bps']:.1f}" if a["cost_bps"] is not None else "-"
        print(f"{a['provider']:<12}{a['verdict']:<9}{rate:>10}{cost:>12}")
    print(f"\naction: {result['action']}\n{result['message']}")


if __name__ == "__main__":
    main()
