# Tangem Quote Guard

A pre-trade check for AI agents that swap crypto through the [Tangem MCP server](https://mcp.tangem.com/en/docs/).

Tangem lets an AI assistant *prepare* a swap and send you a link to sign it in the Tangem app. Before that link is created, though, nothing checks whether the quote is actually any good. Quote Guard fills that gap. It quotes every available provider, prices each quote against an independent market reference, and tells the agent whether it may go ahead.

```
user: "swap 1 ETH to USDC"
  │
  ├─ Tangem  express__pairs            → which providers quote ETH/USDC
  ├─ Tangem  express__exchange_quote   → one quote per provider
  ├─ Guard   check_swap_quotes         → rank by cost vs CoinGecko mid, verdict
  └─ Tangem  express__exchange_intent_create   (only if verdict allows)
               → deeplink → user signs in the Tangem app
```

## The maths

For a quote that turns $q_{\text{in}}$ units of token $A$ into $q_{\text{out}}$ units of token $B$, with reference USD prices $p_A, p_B$ and any separate fee $f$ (in USD):

$$
\text{cost}_{\text{bps}} = \left(1 - \frac{q_{\text{out}}\,p_B - f}{q_{\text{in}}\,p_A}\right) \times 10^4
$$

This is the execution cost relative to mid: the provider's spread and fees combined, measured against what the same value would be worth at the reference price. Amounts arrive from Tangem in minor units, so each one is first scaled as $q = q_{\text{minor}} / 10^{d}$, where $d$ is the token's `decimals`.

With a tolerance $\tau$ (default $50$ bps $= 0.5\%$), each quote gets a verdict:

| Verdict | Condition | Agent action |
|---|---|---|
| `PASS` | $\text{cost} \le \tau$ | may create the intent once the user agrees |
| `WARN` | $\tau < \text{cost} \le 2\tau$ | only with explicit user acceptance of the cost |
| `BLOCK` | $\text{cost} > 2\tau$ | do not create an intent |
| `STALE` | `expiredAt` has passed | re-quote |
| `INVALID` | unreadable, or outside provider min/max | do not use |

Quotes are ranked usable-first, then by lowest cost. A quote more than $100$ bps *better* than the reference is flagged, because that usually points to wrong decimals or a bad price feed, not free money.

## Quick start

```bash
pip install -e ".[dev]"
python -m quote_guard.demo     # offline demo with mock quotes
pytest -q                      # 22 tests
```

Demo output (mock providers, ETH at \$3000):

```
provider    verdict        rate  cost (bps)
-------------------------------------------
provider_a  PASS        2988.50        38.3
provider_b  BLOCK       2955.00       150.0
provider_d  BLOCK       2820.00       600.0
provider_c  STALE       2999.00         3.3
```

`provider_c` has the best rate, but its quote has expired, so the guard picks `provider_a`.

## Use it with Tangem in Claude (or any MCP client)

Add **both** servers to your client. Tangem's server handles wallet login (QR scan and OAuth approval in the Tangem app). Quote Guard runs locally and never touches your wallet.

Claude Code:

```bash
claude mcp add --transport http tangem https://mcp.tangem.org/mcp
claude mcp add quote-guard -- python -m quote_guard.server
```

Claude Desktop (`claude_desktop_config.json`), for the local server:

```json
{
  "mcpServers": {
    "quote-guard": { "command": "python", "args": ["-m", "quote_guard.server"] }
  }
}
```

Then ask: *"Swap 0.05 ETH to USDC, but check the quotes with quote guard first."* The server's instructions tell the agent the workflow.

> Check the endpoint domain on Tangem's official site before connecting. The docs are hosted on `tangem.com` and list the endpoint as `mcp.tangem.org`.

## Tools

**`check_swap_quotes(from_token, to_token, quotes, max_cost_bps=50, price_from_usd=None, price_to_usd=None, from_amount_minor=None)`**

- `from_token` / `to_token` take `{"symbol", "network", "contractAddress", "decimals"}`, with `"0"` as the contract address for a native coin, as in Tangem's API.
- `quotes` takes `[{"provider", "rateType", "response": <raw express__exchange_quote result>}]`.
- It returns `recommendation`, `action` (`OK_TO_CREATE_INTENT`, `ASK_USER`, `REQUOTE`, `DO_NOT_SWAP` or `STOP`), a `message` for the agent, and per-quote assessments.
- If no manual price is given, reference prices come from CoinGecko's free API.

**`explain_quote_fields(response)`** shows which fields of a raw quote were read as amounts, min/max, expiry and fee.

## Known gaps

- Tangem's docs say a quote contains amounts, min/max, fees and `expiredAt`, but they don't publish the exact field names for the amounts or fees. The parser in `quote_guard/parse.py` matches several likely names. If a live response uses different names, run `explain_quote_fields` and add the pattern.
- Fees are only counted separately if they're reported in USD (or passed as `fee_usd`). Fees already taken out of the output amount are captured automatically.
- The reference price is a spot mid from CoinGecko, so it can lag fast markets by a minute or so. On very volatile pairs, a tighter tolerance may cause false `WARN`s.

## Project layout

```
quote_guard/
  core.py      cost maths, verdicts, ranking
  parse.py     tolerant parser for express__exchange_quote responses
  prices.py    CoinGecko reference prices (stdlib only)
  service.py   the check, independent of MCP
  server.py    MCP server (works with mcp SDK v1 and v2)
  demo.py      offline demo with mock data
tests/         pytest suite
```

Built at *Build on Tangem: MCP Workshop & Build Night*, Encode Hub London.
