"""
bnb-airdrop-autopilot - a complete system for BSC airdrops & free mints.

Registers four model-callable tools (all read-only except prepare, which
only PREVIEWS a transaction and never executes):

* bnb_scan_airdrops  - find new BSC tokens (Dexscreener, no login needed)
* bnb_check_contract - safety audit of one contract (owner, proxy,
  approvals in bytecode, Sourcify verification, DEX liquidity, risk rating)
* bnb_prepare_claim  - preview a claim call via baw (returns requestId;
  NOTHING is broadcast; to execute, the user runs the command themselves
  in their own terminal - the agent never runs it)
* bnb_gas_report     - current BSC gas price + cheapest-claim recommendation

Safe by design: the plugin never auto-executes, never signs, and never
spends. A claim only moves when the user runs the execute command
themselves in their own terminal.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from tools.registry import tool_error, tool_result

from . import executor as _executor
from . import notifier as _notifier
from . import safety as _safety
from . import scanner as _scanner
from ._evm_base import CHAINS, _rpc

logger = logging.getLogger(__name__)

_ADDR_RE = __import__("re").compile(r"^0x[0-9a-fA-F]{40}$")


# ---------------------------------------------------------------- schemas
SCAN_SCHEMA = {
    "description": (
        "Scan for newly listed BSC tokens (free-mint / airdrop candidates) "
        "via Dexscreener's public API. Returns the newest BSC token profiles. "
        "These are NEW tokens, not confirmed airdrops - always run "
        "bnb_check_contract on an address before any claim."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "How many candidates to return (1-20). Defaults to 10.",
                "minimum": 1,
                "maximum": 20,
            }
        },
        "additionalProperties": False,
    },
}

CHECK_SCHEMA = {
    "description": (
        "Safety-audit one token contract before interacting with it. Returns "
        "name, symbol, supply, owner/renounced status, proxy detection, "
        "approval selectors in the bytecode, Sourcify verification, the DEX "
        "V2 pair + liquidity, and a HIGH/MEDIUM/LOW risk rating with reasons. "
        "Read-only; public RPCs, no API key, no signing."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "address": {
                "type": "string",
                "description": "Token contract address (0x + 40 hex chars).",
            },
            "chain": {
                "type": "string",
                "description": "Chain: bsc, ethereum, base or arbitrum. Defaults to bsc.",
                "enum": ["bsc", "ethereum", "base", "arbitrum"],
            },
        },
        "required": ["address"],
        "additionalProperties": False,
    },
}

PREPARE_SCHEMA = {
    "description": (
        "PREVIEW a claim transaction via the baw CLI (Binance Agentic Wallet). "
        "This only simulates the call and returns the preview (requestId, "
        "value, gas, risk). NOTHING is broadcast and nothing is signed. "
        "To execute, the user runs the execute command themselves in their "
        "own terminal (the agent cannot run it). "
        "Use this when the user asks to prepare a claim for a contract address "
        "and calldata they provide."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "contract": {
                "type": "string",
                "description": "Contract address to call (0x + 40 hex chars).",
            },
            "input_data": {
                "type": "string",
                "description": "EVM calldata, 0x-prefixed hex (e.g. the claim() call).",
            },
            "from_address": {
                "type": "string",
                "description": "The agent wallet address that would send the tx.",
            },
            "value_wei": {
                "type": "string",
                "description": "Value in wei (default '0'). A claim should be 0 unless the user says otherwise.",
            },
            "chain_id": {
                "type": "integer",
                "description": "Binance chain ID (56 = BSC). Defaults to 56.",
            },
        },
        "required": ["contract", "input_data", "from_address"],
        "additionalProperties": False,
    },
}

GAS_SCHEMA = {
    "description": (
        "Current BSC gas report: gas price (gwei), recent base-fee trend, and "
        "a cheapest-claim recommendation. Read-only; public BSC RPC."
    ),
    "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
}


# ---------------------------------------------------------------- handlers
def _handle_scan(args: dict, **kwargs: Any) -> str:
    del kwargs
    limit = args.get("limit") or 10
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(20, limit))
    try:
        result = _scanner.scan_airdrops(limit=limit)
    except Exception as exc:  # noqa: BLE001 - surface failures cleanly
        return tool_error("scan failed: %s" % exc)
    if not result.get("success"):
        return tool_error(result.get("error") or "scan failed")
    result["telegram_message"] = _notifier.format_scan_message(result)
    return tool_result(result)


def _handle_check(args: dict, **kwargs: Any) -> str:
    del kwargs
    address = args.get("address")
    if not isinstance(address, str) or not _ADDR_RE.match(address.strip()):
        return tool_error("address must be a 0x contract address (40 hex chars)")
    chain = args.get("chain") or "bsc"
    if chain not in CHAINS:
        return tool_error("chain must be one of: bsc, ethereum, base, arbitrum", got=str(chain))
    try:
        result = _safety.check_contract(address.strip(), chain)
    except ValueError as exc:
        return tool_error(str(exc), address=address, chain=chain)
    except Exception as exc:  # noqa: BLE001 - surface RPC failures cleanly
        logger.warning("bnb_check_contract RPC failure: %s", exc)
        return tool_error("contract check failed: %s" % exc, address=address, chain=chain)
    result["telegram_message"] = _notifier.format_risk_message(result)
    return tool_result({"success": True, "contract": result})


def _handle_prepare(args: dict, **kwargs: Any) -> str:
    del kwargs
    try:
        result = _executor.prepare_claim(
            contract=args.get("contract") or "",
            input_data=args.get("input_data") or "0x",
            from_address=args.get("from_address") or "",
            chain_id=int(args.get("chain_id") or 56),
            value_wei=str(args.get("value_wei") or "0"),
        )
    except (ValueError, RuntimeError) as exc:
        return tool_error(str(exc))
    except Exception as exc:  # noqa: BLE001 - surface failures cleanly
        return tool_error("prepare_claim failed: %s" % exc)
    return tool_result(result)


def _handle_gas(args: dict, **kwargs: Any) -> str:
    del kwargs
    rpc_urls = CHAINS["bsc"]["rpcs"]
    try:
        gas_hex = _rpc(rpc_urls, "eth_gasPrice", [])
        gas_wei = int(gas_hex, 16)
        gas_gwei = gas_wei / 1e9
        block = _rpc(rpc_urls, "eth_getBlockByNumber", ["latest", False])
        base_fee_wei = int(block.get("baseFeePerGas", "0x0"), 16) if isinstance(block, dict) else 0
        base_fee_gwei = base_fee_wei / 1e9
    except Exception as exc:  # noqa: BLE001 - surface RPC failures cleanly
        return tool_error("gas report failed: %s" % exc)
    # A plain claim is roughly 100-200k gas; show the cost at current price.
    est_claim_bnb = (gas_wei * 150000) / 1e18
    if gas_gwei <= 0.2:
        rec = "Gas is VERY cheap (<=0.2 gwei) - a great time to claim."
    elif gas_gwei <= 1.0:
        rec = "Gas is cheap (<=1 gwei) - still fine to claim now."
    elif gas_gwei <= 3.0:
        rec = "Gas is moderate (<=3 gwei) - you can claim, but waiting a bit may be cheaper."
    else:
        rec = "Gas is EXPENSIVE (>3 gwei) - better to wait for gas to drop before claiming."
    return tool_result(
        {
            "success": True,
            "chain": "bsc",
            "gas_price_gwei": round(gas_gwei, 4),
            "base_fee_gwei": round(base_fee_gwei, 4),
            "estimated_claim_cost_bnb_150k_gas": round(est_claim_bnb, 6),
            "recommendation": rec,
        }
    )


# ---------------------------------------------------------------- register
def register(ctx: Any) -> None:
    """Plugin entry point - expose the four Autopilot tools."""
    ctx.register_tool(
        name="bnb_scan_airdrops",
        toolset="bnb_airdrop_autopilot",
        schema=SCAN_SCHEMA,
        handler=_handle_scan,
        description="Scan for newly listed BSC tokens (free-mint / airdrop candidates).",
    )
    ctx.register_tool(
        name="bnb_check_contract",
        toolset="bnb_airdrop_autopilot",
        schema=CHECK_SCHEMA,
        handler=_handle_check,
        description="Safety-audit one token contract (owner, proxy, approvals, liquidity, risk).",
    )
    ctx.register_tool(
        name="bnb_prepare_claim",
        toolset="bnb_airdrop_autopilot",
        schema=PREPARE_SCHEMA,
        handler=_handle_prepare,
        description="PREVIEW a claim transaction via baw (preview only; the user runs the execute command themselves).",
    )
    ctx.register_tool(
        name="bnb_gas_report",
        toolset="bnb_airdrop_autopilot",
        schema=GAS_SCHEMA,
        handler=_handle_gas,
        description="Current BSC gas price + cheapest-claim recommendation.",
    )
    logger.debug("bnb-airdrop-autopilot: registered 4 tools")
