"""
executor.py - prepare a claim transaction via baw (preview ONLY, never execute).

This module shells out to the Binance Agentic Wallet CLI (`baw`) to preview
a contract call. Preview is read-only: it simulates the call and returns
the requestId, value, gas and risk assessment WITHOUT broadcasting anything.

Execution is deliberately NOT implemented here, and the preview result
never tells the model to run the execute command. To execute, the user
runs `baw contract-call execute --requestId <id>` THEMSELVES in their own
terminal. The plugin never auto-executes.

baw must be installed and paired on the machine running Hermes. The binary
is located via PATH (shutil.which), so it works on the VM and on Termux.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from typing import Any

logger = logging.getLogger(__name__)

_ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_HEX_RE = re.compile(r"^0x[0-9a-fA-F]*$")
_NON_NEG_INT_RE = re.compile(r"^(0|[1-9][0-9]*)$")


def _minimal_env() -> dict[str, str]:
    """Minimal environment for subprocess calls.

    The child must NOT inherit the full Hermes environment (which holds
    provider API keys). Only an explicit allowlist is passed through:

    * PATH (to resolve the binary), HOME (baw keeps its session under
      ~/.baw) and LANG.
    * The host's egress proxy + custom CA bundle vars (http_proxy,
      https_proxy, all_proxy, no_proxy and their uppercase forms,
      CURL_CA_BUNDLE, SSL_CERT_FILE, NODE_EXTRA_CA_CERTS) — this host
      routes ALL outbound traffic through an egress proxy with its own
      CA, so without them no network call succeeds at all. These are
      host network config, not provider API keys; no API key is passed.
    """
    env: dict[str, str] = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    if os.environ.get("HOME"):
        env["HOME"] = os.environ["HOME"]
    env["LANG"] = os.environ.get("LANG", "C.UTF-8")
    for key in (
        "http_proxy",
        "https_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "all_proxy",
        "ALL_PROXY",
        "no_proxy",
        "NO_PROXY",
        "CURL_CA_BUNDLE",
        "SSL_CERT_FILE",
        "NODE_EXTRA_CA_CERTS",
        "NODE_USE_ENV_PROXY",
    ):
        if os.environ.get(key):
            env[key] = os.environ[key]
    return env


def _validate_value_wei(value_wei: str) -> str:
    """value_wei must be a non-negative integer (decimal string)."""
    value = (value_wei or "0").strip()
    if not _NON_NEG_INT_RE.match(value):
        raise ValueError("value_wei must be a non-negative integer (wei as a decimal string)")
    return value


def _find_baw() -> str | None:
    found = shutil.which("baw")
    if found:
        return found
    home = os.path.expanduser("~")
    for cand in (
        os.path.join(home, ".npm-global", "bin", "baw"),
        os.path.join(home, "workspace", "bin", "baw"),
        "/usr/local/bin/baw",
    ):
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


def prepare_claim(
    contract: str,
    input_data: str,
    from_address: str,
    chain_id: int = 56,
    value_wei: str = "0",
) -> dict:
    """Preview a claim call. Returns the preview (no execution)."""
    contract = contract.strip()
    if not _ADDR_RE.match(contract):
        raise ValueError("contract must be a 0x address (40 hex chars)")
    contract = "0x" + contract[2:].lower()
    from_address = from_address.strip()
    if not _ADDR_RE.match(from_address):
        raise ValueError("from_address must be a 0x address (40 hex chars)")
    from_address = "0x" + from_address[2:].lower()
    input_data = (input_data or "0x").strip()
    if not _HEX_RE.match(input_data):
        raise ValueError("inputData must be 0x-prefixed hex")
    if not input_data.startswith("0x"):
        input_data = "0x" + input_data
    value_wei = _validate_value_wei(value_wei)

    baw = _find_baw()
    if not baw:
        raise RuntimeError(
            "baw CLI not found on PATH. Install the Binance Agentic Wallet CLI "
            "and pair it (baw auth signin) before preparing a claim."
        )

    cmd = [
        baw,
        "contract-call",
        "preview",
        "--binanceChainId",
        str(chain_id),
        "--from",
        from_address,
        "--to",
        contract,
        "--value",
        value_wei,
        "--inputData",
        input_data,
        "--json",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=_minimal_env())
    except subprocess.TimeoutExpired:
        raise RuntimeError("baw preview timed out after 120s")
    except FileNotFoundError:
        raise RuntimeError("baw CLI not found on PATH")

    out = (proc.stdout or "").strip()
    if proc.returncode != 0:
        raise RuntimeError("baw preview failed: %s" % (proc.stderr or out)[:500])
    try:
        preview = json.loads(out)
    except Exception:
        raise RuntimeError("baw preview returned non-JSON output: %s" % out[:300])

    # requestId lives at preview.data.requestId in baw's JSON
    req_id = preview.get("requestId") or preview.get("request_id")
    if not req_id and isinstance(preview.get("data"), dict):
        req_id = preview["data"].get("requestId") or preview["data"].get("request_id")
    return {
        "success": True,
        "preview": preview,
        "request_id": req_id,
        "note": (
            "PREVIEW ONLY - nothing was broadcast and nothing was signed. "
            "To execute, run this command YOURSELF in your own terminal "
            "(the agent cannot run it for you): "
            "baw contract-call execute --requestId <request_id>"
        ),
    }
