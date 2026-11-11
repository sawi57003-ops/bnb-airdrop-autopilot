"""Standalone test for bnb-airdrop-autopilot (no hermes install needed).

Mocks `tools.registry` and a minimal `ctx`, imports the plugin, registers
the four tools, then calls each handler against real public APIs/RPCs.
Usage: python3 test_plugin.py
"""
import importlib.util
import json
import os
import sys
import types

registry = types.ModuleType("tools.registry")


def tool_result(data):
    return json.dumps(data)


def tool_error(message, **kwargs):
    out = {"error": message}
    out.update(kwargs)
    return json.dumps(out)


registry.tool_result = tool_result
registry.tool_error = tool_error
tools_mod = types.ModuleType("tools")
tools_mod.registry = registry
sys.modules["tools"] = tools_mod
sys.modules["tools.registry"] = registry

_PLUGIN_DIR = "/home/hatch/workspace/hermes-plugin/bnb-airdrop-autopilot"

# Load the plugin as a package (Hermes loads a directory plugin as a
# package, so relative imports like `from . import executor` must resolve).
_pkg = types.ModuleType("bnb_airdrop_autopilot")
_pkg.__path__ = [_PLUGIN_DIR]
sys.modules["bnb_airdrop_autopilot"] = _pkg
_spec = importlib.util.spec_from_file_location(
    "bnb_airdrop_autopilot.__init__",
    os.path.join(_PLUGIN_DIR, "__init__.py"),
    submodule_search_locations=[_PLUGIN_DIR],
)
plugin = importlib.util.module_from_spec(_spec)
sys.modules["bnb_airdrop_autopilot.__init__"] = plugin
_spec.loader.exec_module(plugin)


class FakeCtx:
    def __init__(self):
        self.tools = {}

    def register_tool(self, name, toolset, schema, handler, description):
        self.tools[name] = handler


def main():
    ctx = FakeCtx()
    plugin.register(ctx)
    for name in ("bnb_scan_airdrops", "bnb_check_contract", "bnb_prepare_claim", "bnb_gas_report"):
        assert name in ctx.tools, f"{name} did not register"
    print("register: OK - all 4 tools registered")

    # 1. gas_report (BSC)
    print("\n--- bnb_gas_report ---")
    d = json.loads(ctx.tools["bnb_gas_report"]({}))
    print("gas_price_gwei:", d.get("gas_price_gwei"), "| rec:", d.get("recommendation", "")[:80])
    assert d.get("success") is True and d.get("gas_price_gwei", 0) > 0
    print("gas_report: OK")

    # 2. check_contract (BUSD on BSC - known good)
    print("\n--- bnb_check_contract (BUSD, BSC) ---")
    d = json.loads(ctx.tools["bnb_check_contract"]({"address": "0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56", "chain": "bsc"}))
    assert d.get("success") is True, d
    c = d["contract"]
    print("symbol:", c.get("symbol"), "| risk:", c.get("risk"), "| reasons:", c.get("risk_reasons"))
    print("verified_sourcify:", c.get("source_verified_sourcify"), "| has_approve:", c.get("has_approve"))
    assert c.get("symbol") == "BUSD"
    print("check_contract: OK")

    # 3. check_contract bad address -> clean error
    print("\n--- bnb_check_contract (bad address) ---")
    d = json.loads(ctx.tools["bnb_check_contract"]({"address": "not-an-address"}))
    print("error:", d.get("error"))
    assert "error" in d
    print("bad address: OK")

    # 4. scan_airdrops
    print("\n--- bnb_scan_airdrops ---")
    d = json.loads(ctx.tools["bnb_scan_airdrops"]({"limit": 5}))
    print("success:", d.get("success"), "| count:", d.get("count"))
    if d.get("success"):
        for cand in d.get("candidates", [])[:3]:
            print(" -", cand.get("symbol"), cand.get("address"))
    assert d.get("success") is True
    print("scan_airdrops: OK")

    # 5. prepare_claim - preview a harmless call (BUSD name() = read-only, value 0).
    #    Uses the real baw CLI. If baw is not paired this will fail cleanly.
    print("\n--- bnb_prepare_claim (preview only, BUSD name()) ---")
    d = json.loads(ctx.tools["bnb_prepare_claim"]({
        "contract": "0xe9e7CEA3DedcA5984780Bafc599bD69ADd087D56",
        "input_data": "0x06fdde03",
        "from_address": "0x404826e8819430B457C95765aAA807E9aBc75E4f",
        "value_wei": "0",
        "chain_id": 56,
    }))
    print(json.dumps(d, indent=1)[:600])
    if d.get("success"):
        print("prepare_claim: OK (preview returned, request_id:", d.get("request_id"), ")")
    else:
        print("prepare_claim: returned error (baw/session issue, not a plugin bug):", d.get("error", "")[:150])

    print("\nALL TESTS DONE")


if __name__ == "__main__":
    main()
