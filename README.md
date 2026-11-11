# BNB Chain Airdrop & Free Mint Autopilot

A Hermes plugin that manages BSC airdrops and free mints end-to-end — but
**safe by design**: it never auto-executes, never signs, and never spends.
A claim only moves when the user runs the execute command themselves in
their own terminal.

## Tools

| Tool | What it does |
|---|---|
| `bnb_scan_airdrops` | Find newly listed BSC tokens (Dexscreener public API, no login). These are NEW tokens, not confirmed airdrops — always check before claiming. |
| `bnb_check_contract` | Safety-audit one contract: name/symbol/supply, owner/renounced, EIP-1967 proxy, `approve` / `setApprovalForAll` selectors in the bytecode, Sourcify source verification, DEX V2 pair + liquidity, and a HIGH/MEDIUM/LOW risk rating with reasons. Read-only. |
| `bnb_prepare_claim` | PREVIEW a claim transaction via the `baw` CLI (Binance Agentic Wallet). Returns the preview (requestId, value, gas, risk). **Nothing is broadcast.** To execute, the user runs `baw contract-call execute --requestId <id>` themselves in their own terminal. |
| `bnb_gas_report` | Current BSC gas price (gwei), base fee, estimated claim cost, and a cheapest-claim recommendation. Read-only. |

## Workflow

1. **Scan** — `bnb_scan_airdrops` surfaces new BSC tokens.
2. **Check** — `bnb_check_contract <address>` audits one contract and gives
   a risk rating (HIGH / MEDIUM / LOW) with reasons.
3. **Prepare** — `bnb_prepare_claim <contract> <inputData> <from>` previews
   the claim via `baw contract-call preview` and shows value + gas + risk.
4. **Execute (by hand)** — the user runs
   `baw contract-call execute --requestId <id>` themselves in their own
   terminal; the plugin never runs it.

## Why this exists

Free mints are messy to find and full of scams. This plugin puts the whole
loop in one place: discovery, a fast safety check, a simulated claim, and a
gas-aware recommendation — with the user in control at every step.

## Requirements

- `baw` (Binance Agentic Wallet CLI) installed and paired, for
  `bnb_prepare_claim`. The other three tools only need public RPCs / APIs.
- `curl` on PATH is preferred for RPC calls (its TLS handshake is accepted
  by public RPCs that silently drop Python's stdlib TLS fingerprint);
  the plugin falls back to stdlib `urllib`.

## Disclosure

- Read-only except `bnb_prepare_claim`, which only PREVIEWS (simulates).
  No transaction is broadcast or signed by the plugin.
- Network calls: public BSC/Ethereum/Base/Arbitrum RPCs, Dexscreener public
  API, Sourcify (source verification). No API keys, no credentials read.
- The safety check is an automated on-chain read, not a full audit. It
  cannot detect honeypots, hidden taxes or malicious logic. It is not
  financial advice. Never approve a contract you do not trust.

## License

MIT. See `LICENSE`.
