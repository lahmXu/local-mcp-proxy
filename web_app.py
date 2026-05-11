"""Web 配置管理界面 + REST API（Flask）"""
import json
import os
import secrets
import sys
from pathlib import Path

from flask import Flask, jsonify, redirect, request, send_from_directory, session, url_for

from models import (
    ConfigStorage,
    MCPConfig,
    ProtocolType,
    MySQLConfig,
    HTTPConfig,
    ToolConfig,
)

_LOGIN_META_KEYS = frozenset({"secret_key", "users", "_meta", "_comment"})


def _web_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "web"
    return Path(__file__).resolve().parent / "web"


def _get_secret_key(config_dir: Path) -> str:
    env = os.environ.get("MCP_PROXY_SECRET_KEY")
    if env:
        return env.strip()
    secret_file = config_dir / ".session_secret"
    if secret_file.exists():
        try:
            return secret_file.read_text(encoding="utf-8").strip()
        except OSError:
            pass
    key = secrets.token_hex(32)
    try:
        secret_file.write_text(key, encoding="utf-8")
    except OSError:
        pass
    return key


def _load_login_file(config_dir: Path) -> dict:
    login_file = config_dir / "login_configs.json"
    if login_file.exists():
        try:
            with open(login_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    return {}


def _users_from_login_json(raw: dict) -> dict[str, str]:
    """从 login_configs.json 解析 用户名 -> 密码。"""
    if not raw:
        return {}
    if raw.get("username") and "password" in raw:
        return {str(raw["username"]): str(raw["password"])}
    users = raw.get("users")
    if isinstance(users, dict):
        return {str(k): str(v) for k, v in users.items()}
    return {
        str(k): str(v)
        for k, v in raw.items()
        if k not in _LOGIN_META_KEYS
        and not str(k).startswith("_")
    }


def create_app(storage: ConfigStorage, proxy_manager=None) -> Flask:
    config_dir = storage.config_dir

    app = Flask(__name__, static_folder=None)
    app.config["JSON_AS_ASCII"] = False
    app.secret_key = _get_secret_key(config_dir)

    @app.before_request
    def _require_login():
        path = request.path or ""
        if path in ("/login", "/favicon.ico"):
            return None
        if path == "/api/login" and request.method == "POST":
            return None
        if path == "/api/logout" and request.method == "POST":
            return None
        if path == "/api/check-auth":
            return None
        if path.startswith("/api/"):
            if not session.get("logged_in"):
                return jsonify({"error": "未登录，请先登录"}), 401
            return None
        if not session.get("logged_in"):
            return redirect(url_for("login_page"))
        return None

    # ── 登录 API ────────────────────────────────────────
    @app.route("/login")
    def login_page():
        return send_from_directory(_web_dir(), "login.html")

    @app.route("/api/login", methods=["POST"])
    def login():
        data = request.get_json(force=True, silent=True) or {}
        username = (data.get("username") or "").strip()
        password = data.get("password") or ""
        raw = _load_login_file(config_dir)
        user_map = _users_from_login_json(raw)

        if not user_map:
            return jsonify({"error": "未配置登录账号，请在 configs/login_configs.json 中设置"}), 500

        if username in user_map and user_map[username] == password:
            session["logged_in"] = True
            session["username"] = username
            return jsonify({"ok": True, "username": username})

        return jsonify({"error": "用户名或密码错误"}), 401

    @app.route("/api/logout", methods=["POST"])
    def logout():
        session.clear()
        return jsonify({"ok": True})

    @app.route("/api/check-auth", methods=["GET"])
    def check_auth():
        if session.get("logged_in"):
            return jsonify({"logged_in": True, "username": session.get("username")})
        return jsonify({"logged_in": False})

    # ── 静态页面 ────────────────────────────────────────
    @app.route("/")
    def index():
        return send_from_directory(_web_dir(), "index.html")

    # ── 配置 CRUD API ───────────────────────────────────
    @app.route("/api/configs", methods=["GET"])
    def list_configs():
        configs = storage.list_all()
        return jsonify([c.to_dict() for c in configs])

    @app.route("/api/configs", methods=["POST"])
    def create_config():
        data = request.get_json(force=True)
        err = _validate_payload(data)
        if err:
            return jsonify({"error": err}), 400
        cfg_id = data.get("id") or ConfigStorage.new_id()
        if storage.get(cfg_id):
            return jsonify({"error": "配置已存在"}), 400

        try:
            cfg = _parse_config(cfg_id, data)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        v2 = _validate_config(cfg)
        if v2:
            return jsonify({"error": v2}), 400
        storage.add(cfg)
        _notify_reload()
        return jsonify(cfg.to_dict()), 201

    @app.route("/api/configs/<cfg_id>", methods=["GET"])
    def get_config(cfg_id):
        cfg = storage.get(cfg_id)
        if not cfg:
            return jsonify({"error": "配置不存在"}), 404
        return jsonify(cfg.to_dict())

    @app.route("/api/configs/<cfg_id>", methods=["PUT"])
    def update_config(cfg_id):
        if not storage.get(cfg_id):
            return jsonify({"error": "配置不存在"}), 404
        data = request.get_json(force=True)
        err = _validate_payload(data)
        if err:
            return jsonify({"error": err}), 400
        try:
            cfg = _parse_config(cfg_id, data)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        v2 = _validate_config(cfg)
        if v2:
            return jsonify({"error": v2}), 400
        storage.update(cfg)
        _notify_reload()
        return jsonify(cfg.to_dict())

    @app.route("/api/configs/<cfg_id>", methods=["DELETE"])
    def delete_config(cfg_id):
        if not storage.delete(cfg_id):
            return jsonify({"error": "配置不存在"}), 404
        _notify_reload()
        return jsonify({"ok": True})

    @app.route("/api/configs/<cfg_id>/toggle", methods=["POST"])
    def toggle_config(cfg_id):
        cfg = storage.get(cfg_id)
        if not cfg:
            return jsonify({"error": "配置不存在"}), 404
        cfg.enabled = not cfg.enabled
        storage.update(cfg)
        _notify_reload()
        return jsonify(cfg.to_dict())

    # ── 工具测试 ────────────────────────────────────────
    @app.route("/api/configs/<cfg_id>/test", methods=["POST"])
    def test_connection(cfg_id):
        cfg = storage.get(cfg_id)
        if not cfg:
            return jsonify({"error": "配置不存在"}), 404

        if cfg.protocol == ProtocolType.MYSQL:
            return _test_mysql(cfg)
        elif cfg.protocol == ProtocolType.HTTP:
            return _test_http(cfg)
        return jsonify({"error": "未知协议"}), 400

    # ── MCP 服务详情 ──────────────────────────────────────
    @app.route("/api/services", methods=["GET"])
    def list_services():
        if not proxy_manager:
            return jsonify([])
        return jsonify(proxy_manager.get_tools_detail())

    # ── 状态 ────────────────────────────────────────────
    @app.route("/api/status", methods=["GET"])
    def status():
        configs = storage.list_all()
        enabled = [c for c in configs if c.enabled]
        tool_count = sum(len([t for t in c.tools if t.enabled]) for c in enabled)
        registered = proxy_manager.get_registered_tools() if proxy_manager else []
        return jsonify({
            "total_configs": len(configs),
            "enabled_configs": len(enabled),
            "total_tools": tool_count,
            "registered_tools": registered,
        })

    def _notify_reload():
        if proxy_manager:
            proxy_manager.reload()

    return app


def _validate_payload(data: dict) -> str | None:
    if not (data.get("name") or "").strip():
        return "名称 name 不能为空"
    return None


def _validate_config(cfg: MCPConfig) -> str | None:
    if cfg.protocol == ProtocolType.MYSQL:
        if cfg.protocol_config is None:
            return "MySQL 协议需要填写 protocol_config"
        mc: MySQLConfig = cfg.protocol_config  # type: ignore[assignment]
        if not mc.host or not mc.database:
            return "MySQL 需要 host 与 database"
    elif cfg.protocol == ProtocolType.HTTP:
        if cfg.protocol_config is None or not cfg.protocol_config.base_url:
            return "HTTP 需要 protocol_config.base_url"
    for t in cfg.tools:
        if not (t.name or "").strip():
            return "每个工具需要提供 name"
        for p in t.params:
            if p.name and not str(p.name).isidentifier():
                return f"工具「{t.name}」的参数名须为合法 Python 标识符: {p.name!r}"
        if cfg.protocol == ProtocolType.MYSQL and not (t.sql or "").strip():
            return f"MySQL 工具「{t.name}」需要 sql"
        if cfg.protocol == ProtocolType.HTTP and not (t.path or "").strip():
            return f"HTTP 工具「{t.name}」需要 path"
    return None


def _parse_config(cfg_id: str, data: dict) -> MCPConfig:
    protocol = ProtocolType(data.get("protocol", "http"))
    pc_data = data.get("protocol_config")
    protocol_config = None
    if pc_data:
        if protocol == ProtocolType.MYSQL:
            protocol_config = MySQLConfig.from_dict(pc_data)
        else:
            protocol_config = HTTPConfig.from_dict(pc_data)

    tools = [ToolConfig.from_dict(t) for t in data.get("tools", [])]

    return MCPConfig(
        id=cfg_id,
        name=data.get("name", ""),
        protocol=protocol,
        enabled=data.get("enabled", True),
        protocol_config=protocol_config,
        tools=tools,
    )


def _test_mysql(cfg: MCPConfig) -> tuple:
    import mysql.connector
    mc = cfg.protocol_config
    if not mc:
        return jsonify({"ok": False, "message": "MySQL 连接失败: 未配置 protocol_config"})
    try:
        conn = mysql.connector.connect(
            host=mc.host, port=mc.port, user=mc.user,
            password=mc.password, database=mc.database,
            connection_timeout=5,
        )
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        cursor.close()
        conn.close()
        return jsonify({"ok": True, "message": f"MySQL 连接成功: {mc.database}@{mc.host}:{mc.port}"})
    except Exception as e:
        return jsonify({"ok": False, "message": f"MySQL 连接失败: {e}"})


def _test_http(cfg: MCPConfig) -> tuple:
    import requests as req
    hc = cfg.protocol_config
    if not hc or not hc.base_url:
        return jsonify({"ok": False, "message": "HTTP 连接失败: 未配置 protocol_config 或 base_url"})
    try:
        headers = dict(hc.headers or {})
        if hc.auth_type == "bearer" and hc.auth_token:
            headers["Authorization"] = f"Bearer {hc.auth_token}"
        elif hc.auth_type == "basic" and hc.auth_username:
            import base64
            cred = base64.b64encode(
                f"{hc.auth_username}:{hc.auth_password}".encode()
            ).decode()
            headers["Authorization"] = f"Basic {cred}"

        # 优先用第一个有 path 的工具端点测试
        test_url = hc.base_url.rstrip("/")
        test_path = ""
        for t in cfg.tools:
            if t.enabled and t.path:
                test_path = "/" + t.path.lstrip("/")
                break
        test_url += test_path

        resp = req.get(test_url, headers=headers, timeout=hc.timeout or 10)
        # 尝试解析 JSON 提取可读信息
        try:
            body = resp.json()
            if isinstance(body, dict):
                body_text = body.get("error") or body.get("message") or body.get("msg") or json.dumps(body, ensure_ascii=False)
            else:
                body_text = json.dumps(body, ensure_ascii=False)
        except Exception:
            body_text = resp.text[:200]
        return jsonify({
            "ok": resp.status_code < 500,
            "message": f"HTTP {resp.status_code} ({test_url}): {body_text}",
        })
    except Exception as e:
        return jsonify({"ok": False, "message": f"HTTP 请求失败: {e}"})
