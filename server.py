import sys
from typing import Optional

import mysql.connector
from mysql.connector import pooling
from fastmcp import FastMCP

from config import config

# 创建 MCP server 实例
mcp = FastMCP("mysql-readonly", instructions="MySQL 只读查询工具，支持 SELECT 查询和表结构查看")

# 连接池
_pool: Optional[pooling.MySQLConnectionPool] = None


def get_pool() -> pooling.MySQLConnectionPool:
    """获取或创建连接池"""
    global _pool
    if _pool is None:
        missing = config.validate()
        if missing:
            raise ValueError(f"缺少必要配置: {', '.join(missing)}，请检查 .env 文件")
        _pool = pooling.MySQLConnectionPool(
            pool_name="mcp_pool",
            pool_size=3,
            pool_reset_session=True,
            **config.to_dict(),
        )
    return _pool


def get_connection():
    """从连接池获取连接"""
    pool = get_pool()
    return pool.get_connection()


def is_select_query(sql: str) -> bool:
    """检查是否为 SELECT 查询"""
    normalized = sql.strip().upper()
    # 允许 SELECT、SHOW、DESCRIBE、EXPLAIN
    return normalized.startswith(("SELECT", "SHOW", "DESCRIBE", "EXPLAIN"))


@mcp.tool()
def test_connection() -> str:
    """测试 MySQL 连接是否正常"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        cursor.close()
        conn.close()
        return f"连接成功! 数据库: {config.database}@{config.host}:{config.port}"
    except Exception as e:
        return f"连接失败: {e}"


@mcp.tool()
def list_tables() -> str:
    """列出当前数据库的所有表"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SHOW TABLES")
        tables = cursor.fetchall()
        cursor.close()
        conn.close()

        if not tables:
            return "数据库中没有表"

        result = f"数据库 '{config.database}' 中的表:\n"
        for i, (table,) in enumerate(tables, 1):
            result += f"{i}. {table}\n"
        return result.strip()
    except Exception as e:
        return f"查询失败: {e}"


@mcp.tool()
def describe_table(table_name: str) -> str:
    """查看指定表的结构"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(f"DESCRIBE `{table_name}`")
        columns = cursor.fetchall()
        cursor.close()
        conn.close()

        if not columns:
            return f"表 '{table_name}' 不存在或没有列"

        result = f"表 '{table_name}' 的结构:\n"
        result += f"{'列名':<20} {'类型':<20} {'允许NULL':<10} {'键':<10} {'默认值':<10}\n"
        result += "-" * 70 + "\n"
        for col in columns:
            name, col_type, null, key, default, extra = col
            result += f"{name:<20} {col_type:<20} {null:<10} {key:<10} {str(default):<10}\n"
        return result.strip()
    except Exception as e:
        return f"查询失败: {e}"


@mcp.tool()
def query(sql: str) -> str:
    """执行只读 SQL 查询 (SELECT/SHOW/DESCRIBE/EXPLAIN)

    Args:
        sql: 要执行的 SQL 查询语句
    """
    # 安全检查：只允许只读操作
    if not is_select_query(sql):
        return "错误: 只允许 SELECT/SHOW/DESCRIBE/EXPLAIN 查询，不支持写入操作"

    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(sql)

        if cursor.description:
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            if not rows:
                return "查询返回空结果"

            # 格式化输出
            result = " | ".join(columns) + "\n"
            result += "-" * len(result) + "\n"
            for row in rows:
                result += " | ".join(str(val) for val in row) + "\n"
            return result.strip()
        else:
            cursor.close()
            conn.close()
            return "查询执行成功，无返回数据"
    except Exception as e:
        return f"查询失败: {e}"


def main():
    """主入口"""
    import argparse

    parser = argparse.ArgumentParser(description="MySQL MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="传输方式: stdio (默认) 或 sse",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="SSE 模式监听地址 (默认: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="SSE 模式监听端口 (默认: 8000)",
    )

    args = parser.parse_args()

    if args.transport == "sse":
        mcp.run(transport="sse", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
