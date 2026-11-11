"""
scanner.py - find new free-mint / airdrop candidates on BSC.

Sources that work WITHOUT a login or API key:
* Dexscreener latest token profiles (public API) - newly listed tokens,
  filtered to BSC, with their links (website, twitter, telegram).
* BscScan latest verified contracts are intentionally NOT scraped here
  (fragile HTML, rate-limited); the safety check (safety.py) is the
  per-contract gate instead.

What this does NOT do: it does not read X or Telegram (both need a login
the agent does not have), and it does not promise a token is an airdrop -
it surfaces NEW tokens so the user can run bnb_check_contract on them.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

_DEXSCREENER_PROFILES = "https://api.dexscreener.com/token-profiles/latest/v1"


def _get_json(url: str, timeout: int = 15) -> Any:
    req = urllib.request.Request(
        url, headers={"User-Agent": "bnb-airdrop-autopilot/1.0", "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def scan_airdrops(limit: int = 10) -> dict:
    """Return the newest BSC token profiles from Dexscreener."""
    try:
        profiles = _get_json(_DEXSCREENER_PROFILES)
    except Exception as exc:  # noqa: BLE001 - surface the failure cleanly
        return {"success": False, "error": "dexscreener fetch failed: %s" % exc, "candidates": []}

    if not isinstance(profiles, list):
        return {"success": False, "error": "unexpected dexscreener response", "candidates": []}

    candidates = []
    for p in profiles:
        if not isinstance(p, dict):
            continue
        if (p.get("chainId") or "").lower() != "bsc":
            continue
        addr = p.get("tokenAddress") or ""
        if not addr:
            continue
        links = []
        for link in p.get("links") or []:
            if isinstance(link, dict) and link.get("url"):
                links.append({"type": link.get("type"), "url": link.get("url")})
        candidates.append(
            {
                "address": addr,
                "name": p.get("name"),
                "symbol": p.get("symbol"),
                "description": (p.get("description") or "")[:200],
                "links": links,
                "icon": p.get("icon"),
            }
        )
        if len(candidates) >= limit:
            break

    return {
        "success": True,
        "source": "dexscreener token-profiles/latest (BSC only)",
        "count": len(candidates),
        "candidates": candidates,
        "note": (
            "These are NEW tokens, not confirmed airdrops. "
            "Run bnb_check_contract on an address before any claim. "
            "X/Telegram scanning needs a login the agent does not have."
        ),
    }
