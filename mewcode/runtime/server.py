"""
server.py — HTTP 服务入口
=============================================================

【这个模块做什么】
提供 HTTP 服务的命令行入口：
- 解析命令行参数（host、port）
- 加载配置
- 构建运行时
- 启动 uvicorn 服务器

【启动方式】
python -m mewcode.runtime.server --host 127.0.0.1 --port 8765

【依赖】
- uvicorn: ASGI 服务器（可选依赖）
- fastapi: Web 框架（可选依赖）
安装: pip install mewcode[server]
"""
from __future__ import annotations

import argparse

from mewcode.config import load_config
from mewcode.runtime.bootstrap import build_runtime
from mewcode.runtime.http import create_app


def main() -> None:
    """HTTP 服务入口函数"""
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
