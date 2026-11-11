"""
notifier.py - format scan / risk results as Telegram messages.

Hermes delivers the agent's replies through its messaging gateway
(Telegram, Discord, etc.), so a "notification" here is a formatted text
the agent sends in the chat. These helpers build that text from a scan
or safety-check result. Delivery itself is the gateway's job; this module
only formats.
"""

from __future__ import annotations


def format_scan_message(scan: dict) -> str:
    if not scan.get("success"):
        return "BNB Autopilot scan gagal: %s" % (scan.get("error") or "unknown error")
    cands = scan.get("candidates") or []
    if not cands:
        return "BNB Autopilot scan: tidak ada token BSC baru dari Dexscreener."
    lines = ["BNB Autopilot - %d token BSC baru:" % len(cands)]
    for c in cands:
        lines.append("- %s (%s) %s" % (c.get("name") or "?", c.get("symbol") or "?", c.get("address") or ""))
    lines.append("Jalankan bnb.check_contract <address> sebelum claim apa pun.")
    return "\n".join(lines)


def format_risk_message(check: dict) -> str:
    risk = check.get("risk", "?")
    addr = check.get("address", "?")
    name = check.get("name") or check.get("symbol") or "?"
    lines = [
        "BNB Autopilot - cek kontrak %s (%s)" % (name, addr),
        "Risiko: %s" % risk,
    ]
    for r in check.get("risk_reasons") or []:
        lines.append("- " + r)
    if check.get("pair"):
        lines.append("Pair DEX: %s" % check["pair"])
    if check.get("source_verified_sourcify") is False:
        lines.append("Source: BELUM terverifikasi (Sourcify).")
    elif check.get("source_verified_sourcify") is True:
        lines.append("Source: terverifikasi (Sourcify).")
    lines.append("Jangan approve kontrak yang tidak kamu percaya.")
    return "\n".join(lines)
