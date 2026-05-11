"""协议适配器：MySQL 和 HTTP 的实际执行逻辑"""
import hashlib
import json
import logging
import re
from decimal import Decimal
from typing import Any, Dict, List, Optional

import mysql.connector
import mysql.connector.pooling
import requests

from models import MCPConfig, MySQLConfig, HTTPConfig, ToolConfig, ProtocolType

logger = logging.getLogger("mcp-proxy")


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


# ── 统一调度 ──────────────────────────────────────────────

def execute_tool(
    mcp_config: MCPConfig, tool: ToolConfig, arguments: Dict[str, Any]
) -> str:
    if mcp_config.protocol == ProtocolType.MYSQL:
        return execute_mysql_tool(mcp_config, tool, arguments)
    elif mcp_config.protocol == ProtocolType.HTTP:
        return execute_http_tool(mcp_config, tool, arguments)
    return f"不支持的协议: {mcp_config.protocol}"
