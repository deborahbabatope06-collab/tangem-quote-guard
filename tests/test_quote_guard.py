import asyncio
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from quote_guard.core import Quote, Token, Verdict, assess, rank
from quote_guard.parse import explain_fields, parse_quote
from quote_guard.prices import usd_price
from quote_guard.service import check_swap_quotes

ETH = Token("ETH", 18, "ethereum", "0")
USDC = Token("USDC", 6, "ethereum", "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48")
NOW = datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc)


def q(usdc_out, **kw):
    return Quote("p", ETH, USDC, Decimal(10**18), Decimal(int(usdc_out * 10**6)), **kw)


def test_minor_units():
    assert ETH.to_units(10**18) == 1
    assert USDC.to_units("2500500000") == Decimal("2500.5")


@pytest.mark.parametrize("out,verdict,bps", [
    (3000, Verdict.PASS, 0),
    (2985, Verdict.PASS, 50),     # exactly at tolerance
    (2970, Verdict.WARN, 100),
    (2940, Verdict.BLOCK, 200),
])
def test_cost_and_verdict(out, verdict, bps):
    a = assess(q(out), Decimal(3000), Decimal(1), Decimal(50), NOW)
    assert a.verdict is verdict
    assert a.cost_bps == pytest.approx(Decimal(bps))


def test_fee_counts_as_cost():
    a = assess(q(3000, fee_usd=Decimal(15)), Decimal(3000), Decimal(1), Decimal(50), NOW)
    assert a.cost_bps == pytest.approx(Decimal(50))


def test_expired_quote_is_stale():
    a = assess(q(3000, expires_at=NOW - timedelta(seconds=1)), Decimal(3000), Decimal(1), now=NOW)
    assert a.verdict is Verdict.STALE


def test_below_minimum_is_invalid():
    a = assess(q(3000, min_from_minor=Decimal(2 * 10**18)), Decimal(3000), Decimal(1), now=NOW)
    assert a.verdict is Verdict.INVALID


def test_suspiciously_good_quote_flagged():
    a = assess(q(3100), Decimal(3000), Decimal(1), now=NOW)
    assert any("unusual" in r for r in a.reasons)


def test_rank_prefers_usable_then_cheapest():
    a = assess(q(2990), Decimal(3000), Decimal(1), now=NOW)                      # PASS ~33bps
    b = assess(q(2999), Decimal(3000), Decimal(1), now=NOW)                      # PASS ~3bps
    c = assess(q(3000, expires_at=NOW - timedelta(1)), Decimal(3000), Decimal(1), now=NOW)  # STALE
    a.provider, b.provider, c.provider = "a", "b", "c"
    assert [x.provider for x in rank([c, a, b])] == ["b", "a", "c"]


@pytest.mark.parametrize("resp", [
    {"from": {"amount": str(10**18)}, "to": {"amount": "2990000000"}},
    {"fromAmount": str(10**18), "toAmount": "2990000000"},
    {"quote": {"from_amount": str(10**18), "to_amount": "2990000000"}},
    json.dumps({"toAmount": "2990000000"}),  # from amount supplied separately
    {"content": [{"type": "text", "text": json.dumps({"toAmount": "2990000000"})}]},  # MCP result
])
def test_parser_handles_shapes(resp):
    quote = parse_quote(resp, "p", ETH, USDC, from_amount_minor=str(10**18))
    assert quote.to_amount == Decimal("2990")
    assert quote.from_amount == 1


def test_parser_reads_expiry_and_bounds():
    resp = {"from": {"amount": "1"}, "to": {"amount": "1"}, "minAmount": "5",
            "maxAmount": "9", "expiredAt": "2026-12-01T12:05:00Z"}
    quote = parse_quote(resp, "p", ETH, USDC)
    assert quote.min_from_minor == 5 and quote.max_from_minor == 9
    assert quote.expires_at == NOW + timedelta(minutes=5)
    assert explain_fields(resp)["expiry"] == "expiredAt"


def test_parser_error_lists_fields():
    with pytest.raises(ValueError, match="Fields seen"):
        parse_quote({"weird": 1}, "p", ETH, USDC)


def test_prices_with_fake_fetch():
    def fetch(url):
        if "simple/price" in url:
            return {"ethereum": {"usd": 3000.5}}
        return {"0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": {"usd": 0.9999}}
    assert usd_price(ETH, fetch) == Decimal("3000.5")
    assert usd_price(USDC, fetch) == Decimal("0.9999")
    assert usd_price(Token("X", 18, "unknownchain", "0"), fetch) is None


def _quotes():
    soon = (NOW + timedelta(minutes=5)).isoformat()
    return [
        {"provider": "good", "response": {"from": {"amount": str(10**18)},
                                          "to": {"amount": "2995000000"}, "expiredAt": soon}},
        {"provider": "bad", "response": {"from": {"amount": str(10**18)},
                                         "to": {"amount": "2800000000"}, "expiredAt": soon}},
        {"provider": "broken", "response": {"nothing": True}},
    ]


TOK = {"symbol": "ETH", "network": "ethereum", "contractAddress": "0", "decimals": 18}
TOK2 = {"symbol": "USDC", "network": "ethereum",
        "contractAddress": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", "decimals": 6}


def test_service_end_to_end():
    r = check_swap_quotes(TOK, TOK2, _quotes(), 50, 3000, 1, now=NOW)
    assert r["action"] == "OK_TO_CREATE_INTENT"
    assert r["recommendation"] == "good"
    assert [a["provider"] for a in r["assessments"]] == ["good", "bad"]
    assert r["errors"][0]["provider"] == "broken"


def test_service_blocks_when_all_bad():
    r = check_swap_quotes(TOK, TOK2, _quotes()[1:2], 50, 3000, 1, now=NOW)
    assert r["action"] == "DO_NOT_SWAP" and r["recommendation"] is None


def test_service_stops_without_price():
    r = check_swap_quotes(TOK, TOK2, _quotes(), fetch=lambda url: {})
    assert r["action"] == "STOP"


def test_mcp_server_lists_and_calls_tool():
    from quote_guard.server import mcp
    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    assert {"check_swap_quotes", "explain_quote_fields"} <= names
    soon = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    quote = {"provider": "good", "response": {"to": {"amount": "2995000000"}, "expiredAt": soon}}
    res = asyncio.run(mcp.call_tool("check_swap_quotes", {
        "from_token": TOK, "to_token": TOK2, "quotes": [quote],
        "price_from_usd": 3000, "price_to_usd": 1,
        "from_amount_minor": str(10**18)}))
    assert "OK_TO_CREATE_INTENT" in json.dumps(res, default=str)
