"""应用版本读取。源码与 PyInstaller 构建共用同一份 VERSION 文件。"""
import os
import sys
from pathlib import Path


def get_app_version() -> str:
    env_version = os.environ.get("MCP_PROXY_VERSION", "").strip()
    if env_version:
        return env_version

    roots = []
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
        if hasattr(sys, "_MEIPASS"):
            roots.append(Path(sys._MEIPASS))
    roots.append(Path(__file__).resolve().parent)

    for root in roots:
        version_file = root / "VERSION"
        try:
            version = version_file.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if version:
            return version
    return "unknown"


APP_VERSION = get_app_version()
