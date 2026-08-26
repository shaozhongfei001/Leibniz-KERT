#!/usr/bin/env python3
"""启动 DKWS HTTP API（规格 §13）服务于指定工作区。

用法：python serve_api.py --workspace ../demo_workspace [--port 8100]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", "-w", required=True)
    ap.add_argument("--port", type=int, default=8100)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    from dkws.api.server import create_app

    app = create_app(Path(args.workspace).resolve())
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
