"""python -m dispatcher once|watch|status [--dry-run]"""
import argparse
import sys
import time
from pathlib import Path

from .agent import ProcessSpawner
from .core import Dispatcher
from .git import Git
from .github import GitHub
from .settings import DEFAULT_REGISTRY

POLL_SECONDS = 60


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m dispatcher", description="FactoryKit dispatcher")
    parser.add_argument("command", choices=["once", "watch", "status"])
    parser.add_argument("--dry-run", action="store_true", help="read GitHub and git, change nothing, start nothing")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--home", type=Path, default=Path.home() / "factory", help="state, run logs, temp worktrees")
    args = parser.parse_args(argv)
    d = Dispatcher(args.registry, args.home, GitHub, Git, ProcessSpawner(), dry_run=args.dry_run)
    if args.command == "status":
        d.status()
    elif args.command == "once":
        d.cycle()
    else:
        print(f"FactoryKit dispatcher watching {args.registry} every {POLL_SECONDS}s. Ctrl+C stops it; "
              "running agents keep going and are picked up on restart.", flush=True)
        try:
            while True:
                d.cycle()
                time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            d.save()
            print("Dispatcher stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
