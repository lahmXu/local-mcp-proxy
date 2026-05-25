"""MCP 配置数据模型和存储"""
import json
import uuid
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any, List
from enum import Enum
from pathlib import Path


_INTERNAL_METADATA_KEY = "_mcp_proxy_meta"


class ProtocolType(str, Enum):
    MYSQL = "mysql"
    HTTP = "http"
    FILESYSTEM = "filesystem"


@dataclass
class MySQLConfig:
    host: str
    port: int
    user: str
    password: str
    database: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MySQLConfig":
        return cls(
            host=data.get("host", "localhost"),
            port=int(data.get("port", 3306)),
            user=data.get("user", "root"),
            password=data.get("password", ""),
            database=data.get("database", ""),
        )


@dataclass
class HTTPConfig:
    base_url: str
    timeout: int = 30
    headers: Dict[str, str] = field(default_factory=dict)
    auth_type: str = "none"  # none | basic | bearer
    auth_token: str = ""
    auth_username: str = ""
    auth_password: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HTTPConfig":
        return cls(
            base_url=data.get("base_url", ""),
            timeout=int(data.get("timeout", 30)),
            headers=data.get("headers", {}),
            auth_type=data.get("auth_type", "none"),
            auth_token=data.get("auth_token", ""),
            auth_username=data.get("auth_username", ""),
            auth_password=data.get("auth_password", ""),
        )


@dataclass
class FilesystemConfig:
    root_dir: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FilesystemConfig":
        return cls(
            root_dir=data.get("root_dir", ""),
        )


@dataclass
class ToolParam:
    name: str
    type: str = "string"
    description: str = ""
    required: bool = True
    default: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolParam":
        return cls(
            name=data.get("name", ""),
            type=data.get("type", "string"),
            description=data.get("description", ""),
            required=data.get("required", True),
            default=data.get("default"),
        )


@dataclass
class ToolConfig:
    name: str
    description: str = ""
    sql: str = ""  # MySQL tool: SQL template
    path: str = ""  # HTTP tool: URL path / Filesystem: relative path
    method: str = "GET"  # HTTP tool: HTTP method
    params: List[ToolParam] = field(default_factory=list)
    enabled: bool = True
    format: str = "json"  # MySQL tool: "text" | "json"
    operation: str = ""  # Filesystem: read_file | list_directory

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolConfig":
        params = [ToolParam.from_dict(p) for p in data.get("params", [])]
        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            sql=data.get("sql", ""),
            path=data.get("path", ""),
            method=data.get("method", "GET"),
            params=params,
            enabled=data.get("enabled", True),
            format=data.get("format", "json"),
            operation=data.get("operation", ""),
        )


@dataclass
class MCPConfig:
    id: str
    name: str
    protocol: ProtocolType
    enabled: bool = True
    protocol_config: Optional[MySQLConfig | HTTPConfig] = None
    tools: List[ToolConfig] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "protocol": self.protocol.value,
            "enabled": self.enabled,
            "protocol_config": self.protocol_config.to_dict() if self.protocol_config else None,
            "tools": [t.to_dict() for t in self.tools],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MCPConfig":
        protocol = ProtocolType(data.get("protocol", "http"))
        pc = data.get("protocol_config")
        if pc:
            if protocol == ProtocolType.MYSQL:
                pc = MySQLConfig.from_dict(pc)
            elif protocol == ProtocolType.HTTP:
                pc = HTTPConfig.from_dict(pc)
            elif protocol == ProtocolType.FILESYSTEM:
                pc = FilesystemConfig.from_dict(pc)
        tools = [ToolConfig.from_dict(t) for t in data.get("tools", [])]
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            protocol=protocol,
            enabled=data.get("enabled", True),
            protocol_config=pc,
            tools=tools,
        )


class ConfigStorage:
    def __init__(self, config_dir: Path = None):
        self.config_dir = config_dir or Path(__file__).parent / "configs"
        self.config_file = self.config_dir / "mcp_configs.json"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self._configs: Dict[str, MCPConfig] = {}
        self._metadata: Dict[str, Any] = {}
        self._load()

    def _load(self):
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                metadata = data.get(_INTERNAL_METADATA_KEY, {})
                self._metadata = metadata if isinstance(metadata, dict) else {}
                self._configs = {
                    cid: MCPConfig.from_dict(cd)
                    for cid, cd in data.items()
                    if cid != _INTERNAL_METADATA_KEY
                }
            except Exception as e:
                print(f"加载配置失败: {e}")
                self._configs = {}
                self._metadata = {}

    def _save(self):
        payload = {cid: c.to_dict() for cid, c in self._configs.items()}
        if self._metadata:
            payload[_INTERNAL_METADATA_KEY] = self._metadata
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(
                payload,
                f,
                indent=2,
                ensure_ascii=False,
            )

    def add(self, config: MCPConfig) -> bool:
        if config.id in self._configs:
            return False
        self._configs[config.id] = config
        self._save()
        return True

    def update(self, config: MCPConfig) -> bool:
        if config.id not in self._configs:
            return False
        self._configs[config.id] = config
        self._save()
        return True

    def delete(self, config_id: str) -> bool:
        if config_id not in self._configs:
            return False
        del self._configs[config_id]
        self._save()
        return True

    def get(self, config_id: str) -> Optional[MCPConfig]:
        return self._configs.get(config_id)

    def list_all(self) -> List[MCPConfig]:
        return list(self._configs.values())

    def list_enabled(self) -> List[MCPConfig]:
        return [c for c in self._configs.values() if c.enabled]

    def get_runtime_metadata(self, key: str) -> Any:
        return self._metadata.get(key)

    def set_runtime_metadata(self, key: str, value: Any) -> None:
        self._metadata[key] = value
        self._save()

    def clear_runtime_metadata(self, key: str) -> None:
        if key in self._metadata:
            del self._metadata[key]
            self._save()

    @staticmethod
    def new_id() -> str:
        return uuid.uuid4().hex[:12]
