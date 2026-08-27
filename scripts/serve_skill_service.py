#!/usr/bin/env python3
"""对外发布 DKWS Skill 执行服务（含知识服务端点）。

- 监听 0.0.0.0:<port>（默认 8100），供 gits 侧 HTTP 调用；
- 自动注入 DeepSeek 模型配置（key 取自 ~/.dsh/.credentials.yaml 的 DEEPSEEK_API_KEY，不落盘、不打印）；
- 未取到 key 时回退确定性适配器（端到端仍可用）。

启动：python serve_skill_service.py [--port 8100] [--workspace <工作区>]
停止：kill $(cat <pidfile>)
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import uvicorn

DEFAULT_WS = Path(__file__).resolve().parent.parent.parent / "bank_front_ws"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8100)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--workspace", default=str(DEFAULT_WS))
    ap.add_argument("--pidfile", default=None)
    args = ap.parse_args()

    # 注入 LLM 配置（key 来自 DSH credentials，不落盘）
    if not os.environ.get("DKWS_LLM_BASE_URL"):
        try:
            import yaml
            cred = yaml.safe_load(open(Path.home() / ".dsh" / ".credentials.yaml"))
            key = (cred or {}).get("DEEPSEEK_API_KEY", "")
            if key:
                os.environ["DKWS_LLM_BASE_URL"] = "https://api.deepseek.com"
                os.environ["DKWS_LLM_API_KEY"] = key
                os.environ["DKWS_LLM_MODEL"] = "deepseek-chat"
                print("[llm] 已注入 DeepSeek（deepseek-chat）", flush=True)
            else:
                print("[llm] 未取到 DEEPSEEK_API_KEY，使用确定性适配器", flush=True)
        except Exception as exc:
            print(f"[llm] credentials 读取失败（{exc}），使用确定性适配器", flush=True)

    from dkws.api.server import create_app
    from dkws.infrastructure.runtime_config import ConfigError, load_runtime_config

    # M2.1/ADR-015：绑定地址纳入配置校验；生产 profile 缺少认证/限流时拒绝启动
    os.environ.setdefault("DKWS_BIND_HOST", args.host)
    try:
        cfg = load_runtime_config()
    except ConfigError as exc:
        raise SystemExit(f"[security] 运行时配置校验失败，拒绝启动：{exc}") from exc
    for warning in cfg.warnings:
        print(f"[security][WARN] {warning}", flush=True)
    if not cfg.auth.enabled:
        print("[security][WARN] 未启用 API Key 认证（dev 模式）；"
              "生产环境请设置 DKWS_PROFILE=prod 与 DKWS_API_KEYS", flush=True)
    else:
        print(f"[security] API Key 认证已启用（{len(cfg.auth.active_keys())} 个密钥，"
              f"请求头 {cfg.auth.header_name}）", flush=True)

    app = create_app(Path(args.workspace).resolve(), runtime_config=cfg)
    if args.pidfile:
        Path(args.pidfile).write_text(str(os.getpid()))
    print(f"[skill] 服务监听 http://{args.host}:{args.port}（workspace={args.workspace}）", flush=True)
    print("[skill] 端点: POST /api/skill/execute | GET /api/skill/health | GET /v1/health", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
