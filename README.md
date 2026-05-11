# mcp-proxy

一个基于 [FastMCP](https://github.com/jlowin/fastmcp) 的本地 MCP 代理服务，用于统一转发 MySQL 和 HTTP 数据源的工具调用。

## 特性

- 通过配置动态注册 MCP 工具，无需编写代码
- 支持 MySQL 只读查询（SELECT/SHOW/DESCRIBE/EXPLAIN）
- 支持 HTTP API 请求转发
- 提供 Web 管理界面，可视化管理工具配置
- 支持 streamable-http 和 stdio 两种传输模式

## 快速开始

### 环境要求

- Python 3.10+
- MySQL（可选，如需使用 MySQL 数据源）

### 安装依赖

```bash
# 使用 Conda 环境
conda create -n mcp python=3.10
conda activate mcp

# 安装依赖
pip install -r requirements.txt
```

### 启动服务

```bash
# streamable-http 模式（默认，端口 9210）
python main.py

# stdio 模式（供 Cursor 等 MCP 客户端直接连接）
python main.py --mcp-transport stdio
```

启动后访问 http://127.0.0.1:9211 进入 Web 管理界面，在界面上配置 MySQL/HTTP 数据源。

## MCP 客户端配置

### Cursor / Claude Desktop（streamable-http）

```json
{
  "mcpServers": {
    "mcp-proxy": {
      "url": "http://localhost:9210/mcp"
    }
  }
}
```

### Cursor / Claude Desktop（stdio）

```json
{
  "mcpServers": {
    "mcp-proxy": {
      "command": "python",
      "args": ["/path/to/main.py", "--mcp-transport", "stdio"]
    }
  }
}
```

## 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--config-dir` | 配置目录路径 | 项目目录下 configs/ |
| `--web-host` | 管理页面监听地址 | 127.0.0.1 |
| `--web-port` | 管理页面端口 | 9211 |
| `--mcp-transport` | MCP 传输模式（stdio / streamable-http） | streamable-http |
| `--mcp-host` | MCP 监听地址 | 127.0.0.1 |
| `--mcp-port` | MCP 端口 | 9210 |
| `--log-level` | 日志级别 | INFO |

## 环境变量

| 变量 | 说明 |
|------|------|
| `MCP_PROXY_CONFIG_DIR` | 配置目录路径（等同于 `--config-dir`） |

## 项目结构

```
├── main.py              # 入口：解析参数，启动 MCP + Web 服务
├── proxy_server.py      # MCP 代理核心：动态注册工具到 FastMCP
├── adapters.py          # 协议适配器：MySQL 和 HTTP 执行逻辑
├── models.py            # 数据模型：配置定义 + JSON 文件存储
├── config.py            # MySQL 全局配置（从环境变量加载）
├── web_app.py           # Flask Web 管理界面 + REST API
├── web/
│   └── index.html       # 前端单页应用
├── configs/
│   └── mcp_configs.json # 工具配置文件（自动生成）
└── requirements.txt     # Python 依赖
```

## 许可证

MIT
