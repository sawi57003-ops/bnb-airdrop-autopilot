"""
safety.py - contract safety check for the BNB Airdrop & Free Mint Autopilot.

Reuses the EVM token inspector's on-chain reads (name, symbol, owner,
proxy, DEX pair + liquidity) and adds:

* bytecode scan for the dangerous approval selectors:
  approve(address,uint256) 0x095ea7b3 and
  setApprovalForAll(address,bool) 0xa22cb465
  (their presence means the contract CAN ask for approvals - a flag, not
  a verdict on its own)
* source verification via Sourcify (free, no API key):
  https://sourcify.dev/server/v2/contract/56/<address>
* a risk rating (HIGH / MEDIUM / LOW) with reasons, so the user can judge
  before any claim.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any

from _evm_base import CHAINS, _decode_address, _decode_string, _decode_uint, _rpc, _try_call

logger = logging.getLogger(__name__)

_SEL_APPROVE = "095ea7b3"
_SEL_SET_APPROVAL_FOR_ALL = "a22cb465"
_SEL_NAME = "06fdde03"
_SEL_SYMBOL = "95d89b41"
_SEL_DECIMALS = "313ce567"
_SEL_TOTAL_SUPPLY = "18160ddd"
_SEL_OWNER = "8da5cb5b"
_ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


def _sourcify_verified(address: str, chain_id: int = 56) -> bool | None:
    """True if Sourcify has a source match, False if not, None if unknown."""
    url = "https://sourcify.dev/server/v2/contract/%d/%s" % (chain_id, address)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "bnb-airdrop-autopilot/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status == 200:
                return True
            return False
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        return None
    except Exception as exc:  # noqa: BLE001 - verification is best-effort
        logger.debug("sourcify check failed: %s", exc)
        return None


def _bytecode_has_selector(bytecode: str, selector: str) -> bool:
    if not bytecode or bytecode == "0x":
        return False
    return selector.lower() in bytecode[2:].lower()


def check_contract(address: str, chain: str = "bsc") -> dict:
    """Full safety check. Returns a dict with facts + a risk rating."""
    address = address.strip()
    if not address.lower().startswith("0x"):
        address = "0x" + address
    address = "0x" + address[2:].lower()
    cfg = CHAINS[chain]
    rpc_urls = cfg["rpcs"]
    chain_id = {"bsc": 56, "ethereum": 1, "base": 8453, "arbitrum": 42161}[chain]

    code = _rpc(rpc_urls, "eth_getCode", [address, "latest"])
    if not code or code == "0x":
        raise ValueError("address has no contract code on %s" % chain)

    out: dict[str, Any] = {"chain": chain, "address": address, "dex": cfg["dex"]}

    name_raw = _try_call(rpc_urls, address, "0x" + _SEL_NAME)
    out["name"] = _decode_string(name_raw) if name_raw else None
    symbol_raw = _try_call(rpc_urls, address, "0x" + _SEL_SYMBOL)
    out["symbol"] = _decode_string(symbol_raw) if symbol_raw else None
    dec_raw = _try_call(rpc_urls, address, "0x" + _SEL_DECIMALS)
    out["decimals"] = _decode_uint(dec_raw) if dec_raw else None
    supply_raw = _try_call(rpc_urls, address, "0x" + _SEL_TOTAL_SUPPLY)
    out["total_supply_raw"] = str(_decode_uint(supply_raw)) if supply_raw else None

    owner_raw = _try_call(rpc_urls, address, "0x" + _SEL_OWNER)
    if owner_raw is None:
        out["owner"] = "n/a (no owner())"
        out["owner_renounced"] = None
    else:
        owner = _decode_address(owner_raw)
        out["owner"] = owner if owner else "n/a (undecodable)"
        out["owner_renounced"] = owner == _ZERO_ADDRESS if owner else None

    # Proxy check (EIP-1967 implementation slot)
    impl_slot = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
    impl = _rpc(rpc_urls, "eth_getStorageAt", [address, impl_slot, "latest"])
    if impl and impl != "0x" + "0" * 64:
        out["is_proxy"] = True
        out["implementation"] = _decode_address(impl)
    else:
        out["is_proxy"] = False
        out["implementation"] = None

    # Approval selectors in the bytecode
    out["has_approve"] = _bytecode_has_selector(code, _SEL_APPROVE)
    out["has_set_approval_for_all"] = _bytecode_has_selector(code, _SEL_SET_APPROVAL_FOR_ALL)
    out["bytecode_len"] = (len(code) - 2) // 2 if code.startswith("0x") else 0

    # Source verification (Sourcify)
    out["source_verified_sourcify"] = _sourcify_verified(address, chain_id)

    # DEX V2 pair + liquidity (reuse the base inspector's pair logic)
    wrapped = cfg["wrapped"]
    factory = cfg["factory"]
    pair_data = (
        "0x" + "e6a43905"
        + address[2:].lower().rjust(64, "0")
        + wrapped[2:].lower().rjust(64, "0")
    )
    pair_raw = _try_call(rpc_urls, factory, pair_data)
    pair = _decode_address(pair_raw) if pair_raw else None
    out["pair"] = pair
    out["has_liquidity_pair"] = pair is not None and pair != _ZERO_ADDRESS
    out["reserves"] = None
    out["liquidity_empty"] = None
    if out["has_liquidity_pair"]:
        res_raw = _try_call(rpc_urls, pair, "0x0902f1ac")
        t0_raw = _try_call(rpc_urls, pair, "0x0dfe1681")
        if res_raw and t0_raw:
            r0 = _decode_uint(res_raw[2:66])
            r1 = _decode_uint(res_raw[66:130])
            token0 = _decode_address(t0_raw)
            if token0 is not None:
                token_reserve, native_reserve = (r0, r1) if token0 == address.lower() else (r1, r0)
                out["reserves"] = {"token": str(token_reserve), "wrapped_native": str(native_reserve)}
                out["liquidity_empty"] = token_reserve == 0 or native_reserve == 0

    # ---- risk rating ----
    reasons: list[str] = []
    risk = "LOW"
    if out["source_verified_sourcify"] is False:
        reasons.append("source NOT verified on Sourcify")
        risk = "MEDIUM"
    if out["has_set_approval_for_all"]:
        reasons.append("bytecode contains setApprovalForAll (can request NFT approvals)")
        risk = "MEDIUM"
    if out["has_approve"] and out["owner_renounced"] is False:
        reasons.append("has approve() and owner is NOT renounced")
        if risk == "LOW":
            risk = "MEDIUM"
    if out["is_proxy"]:
        reasons.append("is a proxy (logic can change via implementation)")
        risk = "MEDIUM"
    if out["has_liquidity_pair"] is False:
        reasons.append("no DEX V2 liquidity pair")
    if out["liquidity_empty"]:
        reasons.append("liquidity pair exists but reserves are empty")
        risk = "MEDIUM"
    if out["owner_renounced"] is False and out["source_verified_sourcify"] is False:
        reasons.append("owner active AND source unverified")
        risk = "HIGH"
    if not reasons:
        reasons.append("no red flags found in this check")

    out["risk"] = risk
    out["risk_reasons"] = reasons
    out["disclaimer"] = (
        "This is an automated on-chain read, not a full audit. "
        "It cannot detect honeypots, hidden taxes or malicious logic. "
        "Never approve a contract you do not trust."
    )
    return out
