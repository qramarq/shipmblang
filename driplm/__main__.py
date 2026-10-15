"""Entry point for ShipMBLang CLI aliases."""

import os
import sys

MODEL_MOVED = "Model training and download moved to the separate ShipLM project: pip install 'shiplm[train]' and run: shiplm {cmd}"


def main():
    if len(sys.argv) < 2:
        print("ShipMBLang - natural language programming for ShipMB")
        print()
        print("Usage:")
        print("  python -m shipmblang compile     Compile natural ShipMBLang sentences")
        print("  python -m shipmblang run         Run natural ShipMBLang sentences")
        print("  python -m shipmblang printurf    Explain a raw code error")
        print("  python -m shipmblang mcp         Run the ShipMBLang MCP server")
        print("  python -m shipmblang onboarding  Print/validate ShipMB onboarding contract")
        print("  python -m shipmblang train|prepare|chat|download  Moved to the separate shiplm project")
        print()
        print("Short alias:")
        print('  python -m shipmb run "Use ShipMB..."')
        return

    cmd = sys.argv[1]
    sys.argv = sys.argv[1:]

    if cmd in ("prepare", "train", "chat", "download"):
        print(MODEL_MOVED.format(cmd=cmd))
        raise SystemExit(2)

    if cmd in ("explain-error", "drip", "printurf"):
        from .error_explainer import main as error_explainer_main

        error_explainer_main()

    elif cmd in ("compile", "ship"):
        from shipmblang.pipelines import main as natural_syntax_main

        natural_syntax_main()

    elif cmd in ("run", "ship-run"):
        from shipmblang.pipelines import run_main as natural_syntax_run_main

        natural_syntax_run_main()

    elif cmd == "mcp":
        from .mcp_server import main as mcp_main

        mcp_main()

    elif cmd in ("onboarding", "onboard"):
        from .onboarding import main as onboarding_main

        raise SystemExit(onboarding_main())

    else:
        print(f"Unknown command: {cmd}")
        print("Run 'python -m shipmblang' for usage.")


if __name__ == "__main__":
    main()
