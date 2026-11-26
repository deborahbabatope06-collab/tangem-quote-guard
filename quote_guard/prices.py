"""Reference USD prices from CoinGecko's free public API (no key needed).

Native coins are looked up by CoinGecko id; ERC-20-style tokens by
contract address on the matching CoinGecko "platform". Network ids follow
Tangem's naming where it is obvious; extend the maps if a network is missing.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from decimal import Decimal
from typing import Callable, Optional

from .core import Token

API = "https://api.coingecko.com/api/v3"

# Tangem network id -> CoinGecko asset platform (for contract lookups)
PLATFORMS = {
    "ethereum": "ethereum",
    "polygon": "polygon-pos",
    "polygon-pos": "polygon-pos",
    "bsc": "binance-smart-chain",
    "binance": "binance-smart-chain",
    "arbitrum": "arbitrum-one",
    "arbitrum-one": "arbitrum-one",
    "optimism": "optimistic-ethereum",
    "base": "base",
    "avalanche": "avalanche",
    "solana": "solana",
    "tron": "tron",
}

# Native coins: Tangem network id -> CoinGecko coin id
NATIVE = {
    "bitcoin": "bitcoin",
    "ethereum": "ethereum",
    "arbitrum": "ethereum",
    "arbitrum-one": "ethereum",
    "optimism": "ethereum",
    "base": "ethereum",
    "polygon": "polygon-ecosystem-token",
    "polygon-pos": "polygon-ecosystem-token",
    "bsc": "binancecoin",
    "binance": "binancecoin",
    "solana": "solana",
    "avalanche": "avalanche-2",
    "tron": "tron",
    "litecoin": "litecoin",
    "dogecoin": "dogecoin",
}

Fetcher = Callable[[str], dict]


def _http_get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"accept": "application/json",
                                               "user-agent": "tangem-quote-guard"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


def usd_price(token: Token, fetch: Fetcher = _http_get) -> Optional[Decimal]:
    net = token.network.lower()
    if token.contract_address in ("", "0", None):
        coin = NATIVE.get(net)
        if not coin:
            return None
        data = fetch(f"{API}/simple/price?ids={coin}&vs_currencies=usd")
        v = data.get(coin, {}).get("usd")
    else:
        platform = PLATFORMS.get(net)
        if not platform:
            return None
        addr = token.contract_address.lower()
        q = urllib.parse.urlencode({"contract_addresses": addr, "vs_currencies": "usd"})
        data = fetch(f"{API}/simple/token_price/{platform}?{q}")
        v = {k.lower(): val for k, val in data.items()}.get(addr, {}).get("usd")
    return Decimal(str(v)) if v is not None else None
