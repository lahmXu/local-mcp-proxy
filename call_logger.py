"""工具调用日志记录器：按天存储 JSON 文件，支持跨天检索"""
import atexit
import json
import logging
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("local-mcp-proxy")

_RESULT_PREVIEW_LEN = 500

_TIME_RANGE_MAP = {
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
}


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _format_result_preview(raw: str) -> str:
    """尝试将结果格式化为 pretty JSON，失败则截断原文。"""
    if not raw:
        return ""
    try:
        obj = json.loads(raw)
        return json.dumps(obj, ensure_ascii=False, indent=2)
    except (json.JSONDecodeError, TypeError):
        return raw[:_RESULT_PREVIEW_LEN]


class CallLogger:
    """工具调用日志，按天存储到 logs/call_logs/YYYY-MM-DD.json。"""

    def __init__(self, log_dir: Path, enabled: bool = True):
        self._dir = log_dir / "call_logs"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._enabled = enabled
        self._lock = Lock()
        # 当天缓存：快速追加，定期刷盘
        self._today_date: str = _today_str()
        self._today_entries: List[Dict] = []
        self._dirty = False
        # 加载今天的已有数据
        self._load_today()
        atexit.register(self._flush)

    # ── 开关 ─────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, value: bool):
        self._enabled = value

    # ── 记录 ─────────────────────────────────────────────

    def log(
        self,
        tool_name: str,
        protocol: str,
        arguments: Dict[str, Any],
        result: str,
        duration_ms: float,
        success: bool,
    ):
        if not self._enabled:
            return
        entry = {
            "id": uuid.uuid4().hex[:8],
            "timestamp": _now_str(),
            "tool_name": tool_name,
            "protocol": protocol,
            "arguments": arguments,
            "result_preview": _format_result_preview(result[:_RESULT_PREVIEW_LEN] if result else ""),
            "result_length": len(result) if result else 0,
            "duration_ms": round(duration_ms, 1),
            "success": success,
        }
        with self._lock:
            # 跨天时刷盘旧数据并切换
            today = _today_str()
            if today != self._today_date:
                self._flush()
                self._today_date = today
                self._today_entries = []
            self._today_entries.append(entry)
            self._dirty = True
            self._flush()

    # ── 查询 ─────────────────────────────────────────────

    def query(
        self,
        protocol: Optional[str] = None,
        tool_name: Optional[str] = None,
        success: Optional[bool] = None,
        time_range: Optional[str] = None,
        offset: int = 0,
        limit: int = 50,
    ) -> Tuple[List[Dict], int]:
        """筛选日志，跨天文件检索，返回 (entries, total_count)。"""
        # 确定需要读取哪些日期文件
        dates_to_load = self._dates_for_range(time_range)
        today = _today_str()

        # 非今天的日期从文件加载，今天的用内存缓存（最新）
        other_dates = [d for d in dates_to_load if d != today]
        items = self._load_entries(other_dates)
        with self._lock:
            if today in dates_to_load:
                items.extend(list(self._today_entries))

        # 按时间倒序
        items.sort(key=lambda e: e.get("timestamp", ""), reverse=True)

        # 筛选
        if time_range and time_range in _TIME_RANGE_MAP:
            cutoff = (datetime.now() - _TIME_RANGE_MAP[time_range]).strftime("%Y-%m-%d %H:%M:%S")
            items = [e for e in items if e.get("timestamp", "") >= cutoff]
        if protocol:
            items = [e for e in items if e.get("protocol") == protocol]
        if tool_name:
            keyword = tool_name.lower()
            items = [e for e in items if keyword in e.get("tool_name", "").lower()]
        if success is not None:
            items = [e for e in items if e.get("success") == success]

        total = len(items)
        page = items[offset : offset + limit]
        return page, total

    # ── 内部方法 ─────────────────────────────────────────

    def _file_for_date(self, date_str: str) -> Path:
        return self._dir / f"{date_str}.json"

    def _dates_for_range(self, time_range: Optional[str]) -> List[str]:
        """根据时间范围返回需要检索的日期列表。"""
        today = datetime.now()
        if not time_range or time_range not in _TIME_RANGE_MAP:
            # 无范围：加载所有已有文件
            return sorted(
                f.stem for f in self._dir.glob("*.json")
                if len(f.stem) == 10 and f.stem[4] == "-" and f.stem[7] == "-"
            )
        delta = _TIME_RANGE_MAP[time_range]
        # 多取一天以覆盖边界
        start = (today - delta - timedelta(days=1)).strftime("%Y-%m-%d")
        end = today.strftime("%Y-%m-%d")
        dates = []
        current = datetime.strptime(start, "%Y-%m-%d")
        end_dt = datetime.strptime(end, "%Y-%m-%d")
        while current <= end_dt:
            d = current.strftime("%Y-%m-%d")
            if self._file_for_date(d).exists():
                dates.append(d)
            current += timedelta(days=1)
        return dates

    def _load_entries(self, dates: List[str]) -> List[Dict]:
        """从多个日期文件加载日志条目。"""
        entries = []
        for d in dates:
            path = self._file_for_date(d)
            if not path.exists():
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    entries.extend(data)
            except Exception as e:
                logger.warning("加载日志文件 %s 失败: %s", path.name, e)
        return entries

    def _load_today(self):
        """启动时加载今天的日志文件。"""
        path = self._file_for_date(self._today_date)
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self._today_entries = data
                    logger.info("加载 %d 条今日调用日志", len(data))
            except Exception as e:
                logger.warning("加载今日日志失败: %s", e)

    def _flush(self):
        """将当天内存数据写入文件。"""
        if not self._dirty:
            return
        try:
            path = self._file_for_date(self._today_date)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._today_entries, f, ensure_ascii=False)
            self._dirty = False
        except Exception as e:
            logger.error("写入调用日志失败: %s", e)
