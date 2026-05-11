"""MCP Proxy 核心服务 —— 基于 fastmcp 动态注册工具"""
import re
import threading
import logging
from typing import Dict, Any, Callable

from fastmcp import FastMCP
from fastmcp.tools import FunctionTool

from models import ConfigStorage, ToolConfig
from adapters import execute_tool

logger = logging.getLogger("mcp-proxy")


class MCPProxyManager:
    """管理 MCP Proxy 的生命周期和动态工具注册"""

    def __init__(self, storage: ConfigStorage):
        self.storage = storage
        self.mcp: FastMCP = None
        self._tool_map: Dict[str, tuple] = {}  # full_name -> (cfg_id, tool_config)
        self._rebuild_lock = threading.Lock()
        self._rebuild()

    def _rebuild(self):
        """根据当前配置重建工具注册"""
        if self.mcp is None:
            self.mcp = FastMCP(
                "mcp-proxy",
                instructions="MCP 代理服务：统一转发 MySQL/HTTP 数据源的工具调用",
            )
        else:
            # 复用已有实例，清空旧工具
            for name in list(self.mcp._tool_manager._tools.keys()):
                self.mcp._tool_manager._tools.pop(name, None)
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
        exec(compile(src, "<mcp-proxy-tool>", "exec"), ns)
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
        tool_count = len(self._tool_map)
        logger.info(f"配置已重载，当前工具数: {tool_count}")
        return tool_count

    def get_registered_tools(self) -> list:
        return list(self._tool_map.keys())

    def get_tools_detail(self) -> list[dict]:
        """返回所有已注册工具的详细信息。"""
        result = []
        for full_name, (cfg_id, tool_cfg) in self._tool_map.items():
            cfg = self.storage.get(cfg_id)
            result.append({
                "full_name": full_name,
                "config_name": cfg.name if cfg else "",
                "config_id": cfg_id,
                "protocol": cfg.protocol.value if cfg else "",
                "tool_name": tool_cfg.name,
                "description": tool_cfg.description or "",
                "params": [
                    {
                        "name": p.name,
                        "type": p.type,
                        "required": p.required,
                        "default": p.default,
                    }
                    for p in tool_cfg.params
                ],
                "sql": tool_cfg.sql or "",
                "path": tool_cfg.path or "",
                "method": tool_cfg.method or "GET",
                "format": tool_cfg.format or "json",
            })
        return result

    def run(self, transport: str = "streamable-http", host: str = "0.0.0.0", port: int = 9210):
        logger.info(f"启动 MCP Proxy: transport={transport}, host={host}, port={port}")
        if transport == "stdio":
            self.mcp.run(transport="stdio")
        else:
            self.mcp.run(transport="streamable-http", host=host, port=port)
