"""
Nova Assistant — Main Entry Point
Starts the assistant, runs health checks, and enters the main loop.
"""

import sys
import os
from pathlib import Path

# Fix Windows console encoding for Unicode output
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    # Refresh PATH from registry so newly installed tools (FFmpeg, Ollama)
    # are found even in terminal sessions opened before installation
    import subprocess as _sp
    try:
        _machine = _sp.run(
            ['powershell', '-Command',
             '[System.Environment]::GetEnvironmentVariable("Path","Machine")'],
            capture_output=True, text=True, timeout=5
        ).stdout.strip()
        _user = _sp.run(
            ['powershell', '-Command',
             '[System.Environment]::GetEnvironmentVariable("Path","User")'],
            capture_output=True, text=True, timeout=5
        ).stdout.strip()
        os.environ["PATH"] = _machine + ";" + _user
    except Exception:
        pass  # Non-critical — use existing PATH

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import yaml
import argparse
import logging

from core.logger import setup_logging
from system.health_check import run_full_health_check


def load_config(config_path: Path) -> dict:
    """Load YAML configuration file."""
    if not config_path.exists():
        print(f"ERROR: Config file not found: {config_path}")
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def print_banner():
    """Print the Nova startup banner."""
    banner = """
    +==================================================+
    |                                                  |
    |     N   N  OOO  V   V  AAA                       |
    |     NN  N O   O V   V A   A                      |
    |     N N N O   O V   V AAAAA                      |
    |     N  NN O   O  V V  A   A                      |
    |     N   N  OOO    V   A   A                      |
    |                                                  |
    |        Your Local AI Assistant - v0.1.0          |
    |        100% Offline | 100% Free | 100% Yours    |
    |                                                  |
    +==================================================+
    """
    print(banner)


def main():
    parser = argparse.ArgumentParser(
        description="Nova — Your Local AI Assistant"
    )
    parser.add_argument(
        "--config",
        type=str,
        default=str(PROJECT_ROOT / "config" / "settings.yaml"),
        help="Path to settings.yaml",
    )
    parser.add_argument(
        "--health-check",
        action="store_true",
        help="Run health check only and exit",
    )
    parser.add_argument(
        "--skip-health-check",
        action="store_true",
        help="Skip health check on startup",
    )
    args = parser.parse_args()

    # --- Banner ---
    print_banner()

    # --- Load config ---
    config_path = Path(args.config)
    config = load_config(config_path)

    # --- Setup logging ---
    os.chdir(PROJECT_ROOT)
    logger = setup_logging(config)
    logger.info("Nova starting up...")

    # --- Health check ---
    if not args.skip_health_check:
        healthy, results = run_full_health_check(config)
        if args.health_check:
            sys.exit(0 if healthy else 1)
        if not healthy:
            logger.error(
                "Critical health checks failed. "
                "Fix the issues above or run with --skip-health-check."
            )
            sys.exit(1)
    else:
        logger.warning("Health check skipped by user flag.")

    # --- Start assistant loop ---
    logger.info("All checks passed. Initializing Nova...")

    # Phase 1+ will add: voice loop, intent router, tool executor
    # For now, run a simple interactive text loop as a placeholder
    assistant_name = config.get("assistant", {}).get("name", "Nova")

    try:
        from core.assistant_loop import AssistantLoop

        loop = AssistantLoop(config)
        loop.run()
    except ImportError:
        # Phase 0: assistant_loop not yet built — use text fallback
        logger.info(
            "Assistant loop not yet implemented. "
            "Running in text-input mode for testing."
        )
        print(f"\n  {assistant_name} is running in text mode (Phase 0).")
        print(f"  Type 'quit' or 'exit' to stop.\n")

        while True:
            try:
                user_input = input(f"  You > ").strip()
                if user_input.lower() in ("quit", "exit", "q"):
                    print(f"\n  {assistant_name}: Goodbye! 👋\n")
                    break
                if not user_input:
                    continue
                print(
                    f"  {assistant_name}: I heard '{user_input}' "
                    f"— but I can't do much yet (Phase 0). 🚧\n"
                )
            except (KeyboardInterrupt, EOFError):
                print(f"\n  {assistant_name}: Shutting down. Goodbye! 👋\n")
                break

    logger.info("Nova shut down cleanly.")


if __name__ == "__main__":
    main()
