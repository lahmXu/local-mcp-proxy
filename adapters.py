"""协议适配器：MySQL、HTTP 和文件系统的实际执行逻辑"""
import hashlib
import json
import logging
import os
import re
import time
from decimal import Decimal
from typing import Any, Dict, List, Optional

import mysql.connector
import mysql.connector.pooling
import requests

from models import MCPConfig, MySQLConfig, HTTPConfig, FilesystemConfig, ToolConfig, ProtocolType

logger = logging.getLogger("local-mcp-proxy")


def _json_value(v: Any, is_json_col: bool = False) -> Any:
    """将 MySQL 返回值转为可 JSON 序列化的类型，保留原始语义。"""
    if v is None or isinstance(v, (bool, int, float)):
        return v
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8", errors="replace")
    if isinstance(v, str):
        if is_json_col and v and v[0] in ('{', '['):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, ValueError):
                pass
        return v
    return str(v)


# ── MySQL 适配器 ──────────────────────────────────────────

_mysql_pools: Dict[str, mysql.connector.pooling.MySQLConnectionPool] = {}


def _get_mysql_pool(cfg: MySQLConfig) -> mysql.connector.pooling.MySQLConnectionPool:
    key = f"{cfg.host}:{cfg.port}/{cfg.database}"
    if key not in _mysql_pools:
        safe_pool = "p" + hashlib.md5(key.encode("utf-8")).hexdigest()[:24]
        _mysql_pools[key] = mysql.connector.pooling.MySQLConnectionPool(
            pool_name=safe_pool,
            pool_size=3,
            pool_reset_session=True,
            host=cfg.host,
            port=cfg.port,
            user=cfg.user,
            password=cfg.password,
            database=cfg.database,
        )
    return _mysql_pools[key]


def _is_read_only(sql: str) -> bool:
    s = sql.strip().upper()
    return s.startswith(("SELECT", "SHOW", "DESCRIBE", "EXPLAIN"))


def execute_mysql_tool(
    mcp_config: MCPConfig, tool: ToolConfig, arguments: Dict[str, Any]
) -> str:
    cfg: MySQLConfig = mcp_config.protocol_config
    conn = None
    try:
        pool = _get_mysql_pool(cfg)
        conn = pool.get_connection()
        cursor = conn.cursor()
        sql = tool.sql
        # 替换命名参数 :param_name 或 {param_name}
        for pname, pval in arguments.items():
            sql = sql.replace(f":{pname}", str(pval))
            sql = sql.replace("{" + pname + "}", str(pval))

        if not _is_read_only(sql):
            return f"错误: 仅允许只读查询 (SELECT/SHOW/DESCRIBE/EXPLAIN)，当前 SQL: {sql[:80]}"

        logger.debug("执行 SQL: %s", sql)
        cursor.execute(sql)
        if cursor.description:
            columns = [d[0] for d in cursor.description]
            # MySQL JSON type_code = 245
            json_cols = {i for i, d in enumerate(cursor.description) if d[1] == 245}
            rows = cursor.fetchall()
            if not rows:
                return "[]" if tool.format == "json" else "查询返回空结果"
            if tool.format == "json":
                try:
                    result = [dict(zip(columns, [_json_value(v, i in json_cols) for i, v in enumerate(row)])) for row in rows]
                    return json.dumps(result, ensure_ascii=False)
                except (TypeError, ValueError):
                    pass
            header = " | ".join(columns)
            sep = "-" * len(header)
            lines = [header, sep]
            for row in rows:
                lines.append(" | ".join(str(v) for v in row))
            result = "\n".join(lines)
            logger.debug("查询返回 %d 行", len(rows))
            return result
        return "执行成功，无返回数据"
    except Exception as e:
        logger.error("MySQL 执行失败: %s", e, exc_info=True)
        return f"MySQL 执行失败: {e}"
    finally:
        if conn is not None:
            conn.close()


# ── HTTP 适配器 ───────────────────────────────────────────

def _build_http_headers(cfg: HTTPConfig) -> Dict[str, str]:
    headers = dict(cfg.headers or {})
    if cfg.auth_type == "bearer" and cfg.auth_token:
        headers["Authorization"] = f"Bearer {cfg.auth_token}"
    elif cfg.auth_type == "basic" and cfg.auth_username:
        import base64
        cred = base64.b64encode(
            f"{cfg.auth_username}:{cfg.auth_password}".encode()
        ).decode()
        headers["Authorization"] = f"Basic {cred}"
    return headers


def execute_http_tool(
    mcp_config: MCPConfig, tool: ToolConfig, arguments: Dict[str, Any]
) -> str:
    cfg: HTTPConfig = mcp_config.protocol_config
    headers = _build_http_headers(cfg)
    headers.setdefault("Content-Type", "application/json")

    url = cfg.base_url.rstrip("/") + "/" + tool.path.lstrip("/")

    # 路径参数替换
    for pname, pval in arguments.items():
        url = url.replace("{" + pname + "}", str(pval))

    try:
        if tool.method.upper() == "GET":
            # query 参数
            query_params = {k: v for k, v in arguments.items() if "{" + k + "}" not in tool.path}
            resp = requests.get(
                url, params=query_params, headers=headers, timeout=cfg.timeout
            )
        else:
            body = {k: v for k, v in arguments.items() if "{" + k + "}" not in tool.path}
            resp = requests.request(
                method=tool.method.upper(),
                url=url,
                json=body,
                headers=headers,
                timeout=cfg.timeout,
            )

        if resp.ok:
            try:
                return resp.text
            except Exception:
                return resp.text[:2000]
        return f"HTTP {resp.status_code}: {resp.text[:500]}"
    except requests.Timeout:
        return f"请求超时 ({cfg.timeout}s): {url}"
    except Exception as e:
        return f"HTTP 请求失败: {e}"


# ── 文件系统适配器 ─────────────────────────────────────────

_MAX_FILE_SIZE = 1 * 1024 * 1024  # 1MB


def _safe_resolve(root_dir: str, relative_path: str) -> str:
    """将相对路径解析为绝对路径，校验不逃逸出 root_dir。"""
    root_real = os.path.realpath(root_dir)
    resolved = os.path.realpath(os.path.join(root_real, relative_path))
    if not (resolved == root_real or resolved.startswith(root_real + os.sep)):
        raise ValueError(f"路径越权，不能访问根目录以外的路径: {relative_path}")
    return resolved


def _fs_read_file(root_dir: str, file_path: str, encoding: str = "utf-8") -> str:
    abs_path = _safe_resolve(root_dir, file_path)
    if not os.path.isfile(abs_path):
        return f"文件不存在: {file_path}"
    size = os.path.getsize(abs_path)
    if size > _MAX_FILE_SIZE:
        return f"文件过大 ({size} bytes)，超过 {_MAX_FILE_SIZE} bytes 限制: {file_path}"
    try:
        with open(abs_path, "r", encoding=encoding) as f:
            return f.read()
    except UnicodeDecodeError:
        return f"文件不是有效的 {encoding} 编码，可能是二进制文件: {file_path}"


def _fs_list_directory(root_dir: str, dir_path: str = "") -> str:
    abs_path = _safe_resolve(root_dir, dir_path or ".")
    if not os.path.isdir(abs_path):
        return f"目录不存在: {dir_path}"
    entries = []
    try:
        for name in sorted(os.listdir(abs_path)):
            full = os.path.join(abs_path, name)
            stat = os.stat(full)
            entries.append({
                "name": name,
                "type": "directory" if os.path.isdir(full) else "file",
                "size": stat.st_size,
                "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stat.st_mtime)),
            })
    except PermissionError:
        return f"无权限访问目录: {dir_path}"
    return json.dumps(entries, ensure_ascii=False)


def _resolve_fs_path(arguments: Dict[str, Any], tool: ToolConfig) -> str:
    """从 arguments 中解析文件路径：优先取 'path' 键，否则取第一个参数值，最后回退到 tool.path。"""
    if "path" in arguments:
        return str(arguments["path"])
    if arguments:
        return str(next(iter(arguments.values())))
    return tool.path or ""


def execute_filesystem_tool(
    mcp_config: MCPConfig, tool: ToolConfig, arguments: Dict[str, Any]
) -> str:
    cfg: FilesystemConfig = mcp_config.protocol_config
    op = tool.operation
    try:
        if op == "read_file":
            file_path = _resolve_fs_path(arguments, tool)
            encoding = arguments.get("encoding", "utf-8")
            return _fs_read_file(cfg.root_dir, file_path, encoding)
        elif op == "list_directory":
            dir_path = _resolve_fs_path(arguments, tool)
            return _fs_list_directory(cfg.root_dir, dir_path)
        return f"不支持的文件系统操作: {op}"
    except ValueError as e:
        return f"路径校验失败: {e}"
    except Exception as e:
        logger.error("文件系统操作失败: %s", e, exc_info=True)
        return f"文件系统操作失败: {e}"


# ── 统一调度 ──────────────────────────────────────────────

# ── 日志注入点（由 main.py 初始化后设置）──────────────────
_call_logger = None


def set_call_logger(cl):
    global _call_logger
    _call_logger = cl


def _do_execute(
    mcp_config: MCPConfig, tool: ToolConfig, arguments: Dict[str, Any]
) -> str:
    if mcp_config.protocol == ProtocolType.MYSQL:
        return execute_mysql_tool(mcp_config, tool, arguments)
    elif mcp_config.protocol == ProtocolType.HTTP:
        return execute_http_tool(mcp_config, tool, arguments)
    elif mcp_config.protocol == ProtocolType.FILESYSTEM:
        return execute_filesystem_tool(mcp_config, tool, arguments)
    return f"不支持的协议: {mcp_config.protocol}"


def execute_tool(
    mcp_config: MCPConfig, tool: ToolConfig, arguments: Dict[str, Any]
) -> str:
    start = time.monotonic()
    tool_name = f"{mcp_config.name}__{tool.name}"
    try:
        result = _do_execute(mcp_config, tool, arguments)
        duration_ms = (time.monotonic() - start) * 1000
        if _call_logger:
            _call_logger.log(
                tool_name, mcp_config.protocol.value,
                arguments, result, duration_ms, success=True,
            )
        return result
    except Exception as e:
        duration_ms = (time.monotonic() - start) * 1000
        if _call_logger:
            _call_logger.log(
                tool_name, mcp_config.protocol.value,
                arguments, f"异常: {e}", duration_ms, success=False,
            )
        raise
