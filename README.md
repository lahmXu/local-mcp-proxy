# local-mcp-proxy

一个基于 [FastMCP](https://github.com/jlowin/fastmcp) 的本地 MCP 代理服务，用于统一转发 MySQL/HTTP/文件系统数据源的工具调用。

## 特性

- 通过配置动态注册 MCP 工具，无需编写代码
- 支持 MySQL 只读查询（SELECT/SHOW/DESCRIBE/EXPLAIN）
- 支持 HTTP API 请求转发
- 提供 Web 管理界面，可视化管理工具配置
- 支持 streamable-http 和 stdio 两种传输模式

## 界面预览

![登录页面](release/screenshot/login.png)

![配置管理](release/screenshot/config.png)

![MCP 工具列表](release/screenshot/mcp_list.png)

![运行日志](release/screenshot/log.png)

## 下载安装

从 [Releases](https://github.com/lahmXu/local-mcp-proxy/releases) 页面下载压缩包：

| 平台 | 文件名 |
|------|--------|
| macOS (Apple Silicon) | `dist-v0.0.1-darwin-arm64.zip` |

解压后进入目录：

```bash
unzip dist-v0.0.1-darwin-arm64.zip
cd dist-v0.0.1-darwin-arm64
chmod +x local-mcp-proxy start.sh stop.sh
```

目录结构：

```
dist-v0.0.1-darwin-arm64/
├── local-mcp-proxy        # 可执行文件
├── start.sh               # 启动脚本
├── stop.sh                # 停止脚本
├── configs/
│   └── proxy_configs.json # 配置文件（首次启动自动生成）
└── logs/
    └── server.log         # 日志（启动后自动生成）
```

## 启动服务

```bash
# 默认启动（streamable-http 模式，端口 9210）
./start.sh

# 指定端口
./start.sh --port 9212

# stdio 模式（供 Cursor/Claude Code 等客户端直接连接）
./start.sh --stdio
```

启动成功后会显示：

```
==================================================
  MCP 地址:   http://127.0.0.1:9210/mcp
  配置页面:   http://127.0.0.1:9211
  配置文件:   /path/to/configs/
  日志文件:   /path/to/logs/server.log
==================================================
```

## 停止服务

```bash
./stop.sh
```

## MCP 客户端配置

### Claude Code

```bash
# streamable-http 模式
claude mcp add --transport http local-mcp-proxy http://127.0.0.1:9210/mcp

# 全局添加（所有项目可用）
claude mcp add --scope user --transport http local-mcp-proxy http://127.0.0.1:9210/mcp
```

### Cursor / Claude Desktop（streamable-http）

```json
{
  "mcpServers": {
    "local-mcp-proxy": {
      "url": "http://localhost:9210/mcp"
    }
  }
}
```

## Web 管理界面

启动服务后访问 http://127.0.0.1:9211，在界面上配置 MySQL/HTTP 数据源和工具定义。

Web 界面提供：
- MCP 配置的增删改查
- 工具定义管理（参数、SQL/HTTP 配置）
- 连接测试（MySQL/HTTP）
- 服务状态监控
- 默认用户名/密码: admin/admin123

## 命令行参数

### start.sh 参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--stdio` | 使用 stdio 传输模式 | 否（默认 streamable-http） |
| `--host` | MCP 监听地址 | 127.0.0.1 |
| `--port` | MCP 端口 | 9210 |

### local-mcp-proxy 参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--config-dir` | 配置目录路径 | 当前目录下 configs/ |
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

## 从源码构建

如需自行构建可执行文件，参见下方说明。

### 环境要求

- Python 3.10+
- Conda（推荐）

### 构建步骤

```bash
# 创建并激活 Conda 环境
conda create -n mcp python=3.10
conda activate mcp

# 安装依赖
pip install -r requirements.txt

# 直接运行
python main.py

# 打包为可执行文件
./scripts/build.sh
```

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
