"""python -m dispatcher.dashboard [--port 8765]"""
import argparse
import sys
from pathlib import Path

from ..settings import DEFAULT_REGISTRY
from .server import ReadOnlySource, serve


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m dispatcher.dashboard", description="FactoryKit dashboard")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--home", type=Path, default=Path.home() / "factory")
    args = parser.parse_args(argv)
    server = serve(ReadOnlySource(args.registry, args.home / "state" / "dispatcher.json"), args.port)
    print(f"FactoryKit dashboard on http://127.0.0.1:{server.server_address[1]}/ (read-only). "
          "In VS Code: Command Palette > Simple Browser: Show, then paste the address. Ctrl+C stops it.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Dashboard stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
