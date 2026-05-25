"""MCP Proxy 核心服务 —— 基于 fastmcp 动态注册工具"""
import re
import threading
import logging
import time
from typing import Dict, Any, Callable

from fastmcp import FastMCP
from fastmcp.server.middleware import Middleware
from fastmcp.tools import FunctionTool

from models import ConfigStorage, ToolConfig
from adapters import execute_tool

logger = logging.getLogger("local-mcp-proxy")

_CLIENT_VERSION_METADATA_KEY = "mcp_client_versions"


class MCPClientVersionTracker:
    """Track which MCP sessions have fetched the current tool version."""

    def __init__(
        self,
        version_factory: Callable[[], int] | None = None,
        persist_callback: Callable[[dict[str, Any]], None] | None = None,
    ):
        self._version_factory = version_factory or time.time_ns
        self._persist_callback = persist_callback
        self._lock = threading.Lock()
        self.current_version = self._version_factory()
        self.client_versions: Dict[str, int] = {}
        with self._lock:
            self._persist_locked()

    def bump_config_version(self) -> int:
        """Mark tool configuration changed and return the new version."""
        with self._lock:
            next_version = self._version_factory()
            if next_version <= self.current_version:
                next_version = self.current_version + 1
            self.current_version = next_version
            self._persist_locked()
            return self.current_version

    def get_current_version(self) -> int:
        with self._lock:
            return self.current_version

    def mark_tools_listed(self, session_id: str, session: Any, version: int | None = None) -> None:
        """Mark a session as synced after tools/list returns successfully."""
        with self._lock:
            self.client_versions[session_id] = self.current_version if version is None else version
            self._persist_locked()

    async def notify_if_outdated(self, session_id: str, session: Any) -> bool:
        """Notify a known session if it has not fetched the latest tools."""
        with self._lock:
            known_version = self.client_versions.get(session_id)
            current_version = self.current_version
            if known_version is None:
                known_version = 0
                self.client_versions[session_id] = known_version
                self._persist_locked()
            if known_version >= current_version:
                return False

        try:
            await session.send_tool_list_changed()
        except Exception:
            with self._lock:
                self.client_versions.pop(session_id, None)
                self._persist_locked()
            raise
        return True

    def _persist_locked(self) -> None:
        if not self._persist_callback:
            return
        self._persist_callback({
            "current_version": self.current_version,
            "client_versions": dict(self.client_versions),
        })


class ToolListVersionMiddleware(Middleware):
    """Ask outdated MCP clients to refresh tools after config changes."""

    def __init__(self, tracker: MCPClientVersionTracker):
        self.tracker = tracker

    @staticmethod
    def _session_info(context) -> tuple[str, Any] | None:
        fastmcp_context = context.fastmcp_context
        if fastmcp_context.request_context is None:
            return None
        try:
            return fastmcp_context.session_id, fastmcp_context.session
        except RuntimeError:
            return None

    async def on_request(self, context, call_next):
        if context.method != "tools/list":
            session_info = self._session_info(context)
            if session_info is not None:
                session_id, session = session_info
                try:
                    notified = await self.tracker.notify_if_outdated(session_id, session)
                except Exception:
                    logger.warning(
                        "发送工具列表变更通知失败，已移除 MCP session: %s",
                        session_id,
                        exc_info=True,
                    )
                else:
                    if notified:
                        logger.info("已通知 MCP client 刷新工具列表: session=%s", session_id)
        return await call_next(context)

    async def on_list_tools(self, context, call_next):
        listed_version = self.tracker.get_current_version()
        result = await call_next(context)
        session_info = self._session_info(context)
        if session_info is not None:
            session_id, session = session_info
            self.tracker.mark_tools_listed(session_id, session, listed_version)
            logger.debug(
                "MCP client 工具列表版本已同步: session=%s version=%s",
                session_id,
                listed_version,
            )
        return result


class MCPProxyManager:
    """管理 MCP Proxy 的生命周期和动态工具注册"""

    def __init__(self, storage: ConfigStorage):
        self.storage = storage
        self.mcp: FastMCP = None
        self._tool_map: Dict[str, tuple] = {}  # full_name -> (cfg_id, tool_config)
        self._rebuild_lock = threading.Lock()
        self.storage.clear_runtime_metadata(_CLIENT_VERSION_METADATA_KEY)
        self.client_versions = MCPClientVersionTracker(
            persist_callback=lambda metadata: self.storage.set_runtime_metadata(
                _CLIENT_VERSION_METADATA_KEY,
                metadata,
            )
        )
        self._rebuild()

    def _rebuild(self):
        """根据当前配置重建工具注册"""
        if self.mcp is None:
            self.mcp = FastMCP(
                "local-mcp-proxy",
                instructions="MCP 代理服务：统一转发 MySQL/HTTP/文件系统数据源的工具调用",
            )
            self.mcp.add_middleware(ToolListVersionMiddleware(self.client_versions))
        else:
            # 复用已有实例，通过公开 API 清空旧工具，保留 FastMCP 通知机制。
            for name in list(self.mcp._tool_manager._tools.keys()):
                self.mcp.remove_tool(name)
        self._tool_map.clear()

        configs = self.storage.list_enabled()
        for cfg in configs:
            for tool in cfg.tools:
                if not tool.enabled:
                    continue
                full_name = f"{cfg.name}__{tool.name}"
                try:
                    self._register_tool(full_name, cfg.id, tool)
                    self._tool_map[full_name] = (cfg.id, tool)
                except Exception:
                    logger.exception("注册工具失败 %s", full_name)

    def _register_tool(self, full_name: str, cfg_id: str, tool_cfg: ToolConfig):
        """动态注册单个工具到 fastmcp（必须显式签名，禁止 **kwargs）。"""
        type_map = {
            "string": str,
            "integer": int,
            "number": float,
            "boolean": bool,
        }
        parts: list[str] = []
        for p in tool_cfg.params:
            if not str(p.name).isidentifier():
                raise ValueError(
                    f"工具「{tool_cfg.name}」的参数名须为合法 Python 标识符，当前: {p.name!r}"
                )
            tname = type_map.get(p.type, str).__name__
            if p.required:
                parts.append(f"{p.name}: {tname}")
            elif p.default is not None:
                parts.append(f"{p.name}: {tname} = {repr(p.default)}")
            else:
                parts.append(f"{p.name}: {tname} | None = None")
        sig = ", ".join(parts)

        if tool_cfg.params:
            kv_lines = "    _kw = {}\n"
            kv_lines += "\n".join(
                f"    _kw[{repr(p.name)}] = {p.name} if {p.name} is not None else ''"
                for p in tool_cfg.params
            )
        else:
            kv_lines = "    _kw = {}"

        src = f"def _tool_impl({sig}):\n{kv_lines}\n"
        src += f"""    _cfg = _storage.get({repr(cfg_id)})\n"""
        src += """    if not _cfg:\n"""
        src += f"""        return f"配置不存在: {repr(cfg_id)}"\n"""
        src += """    try:\n"""
        src += """        return _execute_tool(_cfg, _tool_cfg, _kw)\n"""
        src += """    except Exception as _e:\n"""
        src += """        return f"工具执行异常: {_e}"\n"""

        ns: dict[str, Any] = {
            "_storage": self.storage,
            "_execute_tool": execute_tool,
            "_tool_cfg": tool_cfg,
        }
        exec(compile(src, "<local-mcp-proxy-tool>", "exec"), ns)
        fn: Callable = ns["_tool_impl"]
        safe_py = re.sub(r"[^a-zA-Z0-9_]", "_", full_name)
        if not safe_py or not (safe_py[0].isalpha() or safe_py[0] == "_"):
            safe_py = "t_" + safe_py
        fn.__name__ = safe_py or "tool"
        fn.__qualname__ = safe_py or "tool"
        fn.__doc__ = tool_cfg.description or full_name

        ft = FunctionTool.from_function(
            fn,
            name=full_name,
            description=tool_cfg.description or full_name,
        )
        self.mcp.add_tool(ft)

    def reload(self):
        """热重载：重新从存储读取配置并重建工具"""
        with self._rebuild_lock:
            self._rebuild()
            config_version = self.client_versions.bump_config_version()
        tool_count = len(self._tool_map)
        logger.info(f"配置已重载，当前工具数: {tool_count}, 配置版本: {config_version}")
        return tool_count

    def get_registered_tools(self) -> list:
        return list(self._tool_map.keys())

    def get_tools_detail(self) -> list[dict]:
        """返回所有配置工具的详细信息，并标记是否已注册为 MCP 工具。"""
        result = []
        registered_names = set(self._tool_map.keys())
        for cfg in self.storage.list_all():
            for tool_cfg in cfg.tools:
                full_name = f"{cfg.name}__{tool_cfg.name}"
                is_registered = full_name in registered_names
                result.append({
                    "full_name": full_name,
                    "config_name": cfg.name,
                    "config_id": cfg.id,
                    "config_enabled": cfg.enabled,
                    "tool_enabled": tool_cfg.enabled,
                    "enabled": cfg.enabled and tool_cfg.enabled,
                    "registered": is_registered,
                    "protocol": cfg.protocol.value,
                    "tool_name": tool_cfg.name,
                    "description": tool_cfg.description or "",
                    "params": [
                        {
                            "name": p.name,
                            "type": p.type,
                            "required": p.required,
                            "default": p.default,
                            "description": p.description,
                        }
                        for p in tool_cfg.params
                    ],
                    "sql": tool_cfg.sql or "",
                    "path": tool_cfg.path or "",
                    "method": tool_cfg.method or "GET",
                    "format": tool_cfg.format or "json",
                    "operation": tool_cfg.operation or "",
                })
        return result

    def run(self, transport: str = "streamable-http", host: str = "0.0.0.0", port: int = 9210):
        logger.info(f"启动 MCP Proxy: transport={transport}, host={host}, port={port}")
        if transport == "stdio":
            self.mcp.run(transport="stdio")
        else:
            self.mcp.run(transport="streamable-http", host=host, port=port)
