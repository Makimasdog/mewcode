from __future__ import annotations

import argparse

from mewcode.config import load_config
from mewcode.runtime.bootstrap import build_runtime
from mewcode.runtime.http import create_app


def main() -> None:
    parser = argparse.ArgumentParser(prog="mewcode-server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise SystemExit("Install the server extra: pip install mewcode[server]") from exc

    config = load_config()
    runtime = build_runtime(config)
    app = create_app(runtime)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
