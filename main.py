#!/usr/bin/env python3
"""
MCP Proxy 统一入口：FastMCP 代理 + Web 配置管理。
默认 streamable-http 模式，同时后台起管理页。
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
from pathlib import Path

from models import ConfigStorage
from proxy_server import MCPProxyManager
from web_app import create_app
from call_logger import CallLogger
from adapters import set_call_logger

logger = logging.getLogger("local-mcp-proxy")


def resolve_config_dir(cli_dir: str | None) -> Path:
    if cli_dir:
        return Path(cli_dir).expanduser().resolve()
    env = os.environ.get("MCP_PROXY_CONFIG_DIR")
    if env:
        return Path(env).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "configs"
    return Path(__file__).resolve().parent / "configs"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="基于 FastMCP 的本地 MCP 代理（MySQL/HTTP/文件系统 转发 + Web 配置）",
    )
    parser.add_argument(
        "--config-dir",
        default=None,
        help="配置与 mcp_configs.json 所在目录；也可用环境变量 MCP_PROXY_CONFIG_DIR",
    )
    parser.add_argument(
        "--web-host",
        default="127.0.0.1",
        help="管理页面监听地址（默认仅本机）",
    )
    parser.add_argument(
        "--web-port",
        type=int,
        default=9211,
        help="管理页面端口",
    )
    parser.add_argument(
        "--mcp-transport",
        choices=("stdio", "streamable-http"),
        default="streamable-http",
        help="MCP 传输：streamable-http（默认）或 stdio",
    )
    parser.add_argument(
        "--mcp-host",
        default="127.0.0.1",
        help="MCP 监听地址（默认仅本机，如需外部访问请谨慎设置）",
    )
    parser.add_argument(
        "--mcp-port",
        type=int,
        default=9210,
        help="MCP 端口（默认 9210）",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    config_dir = resolve_config_dir(args.config_dir)
    storage = ConfigStorage(config_dir=config_dir)
    log_dir = config_dir.parent / "logs"
    call_logger = CallLogger(log_dir)
    set_call_logger(call_logger)
    manager = MCPProxyManager(storage)
    app = create_app(storage, manager, call_logger)

    def run_flask() -> None:
        app.run(
            host=args.web_host,
            port=args.web_port,
            threaded=True,
            use_reloader=False,
        )

    if args.mcp_transport == "stdio":
        threading.Thread(target=run_flask, daemon=True).start()
        print("", file=sys.stderr)
        print("=" * 50, file=sys.stderr)
        print("[local-mcp-proxy] 服务已启动 (stdio 模式)", file=sys.stderr)
        print("=" * 50, file=sys.stderr)
        print(f"  配置页面:   http://{args.web_host}:{args.web_port}", file=sys.stderr)
        print(f"  配置文件:   {config_dir / 'mcp_configs.json'}", file=sys.stderr)
        print(f"  代理配置:   {config_dir / 'proxy_configs.json'}", file=sys.stderr)
        print("=" * 50, file=sys.stderr)
        print("", file=sys.stderr)
        manager.run(transport="stdio")
    else:
        threading.Thread(target=run_flask, daemon=True).start()
        print("", file=sys.stderr)
        print("=" * 50, file=sys.stderr)
        print("[local-mcp-proxy] 服务已启动 (streamable-http 模式)", file=sys.stderr)
        print("=" * 50, file=sys.stderr)
        print(f"  MCP 地址:   http://{args.mcp_host}:{args.mcp_port}/mcp", file=sys.stderr)
        print(f"  配置页面:   http://{args.web_host}:{args.web_port}", file=sys.stderr)
        print(f"  配置文件:   {config_dir / 'mcp_configs.json'}", file=sys.stderr)
        print(f"  代理配置:   {config_dir / 'proxy_configs.json'}", file=sys.stderr)
        print("=" * 50, file=sys.stderr)
        print("", file=sys.stderr)
        manager.run(
            transport="streamable-http",
            host=args.mcp_host,
            port=args.mcp_port,
        )


if __name__ == "__main__":
    main()
