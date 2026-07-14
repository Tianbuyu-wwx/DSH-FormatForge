"""
轻量级指标收集器
纯 Python 实现，无外部依赖，支持 Prometheus 文本格式导出
"""

import logging
import threading
import time

logger = logging.getLogger("metrics")


class _Counter:
    """计数器"""

    def __init__(self, name: str, help_text: str, label_names: list[str] | None = None):
        self.name = name
        self.help = help_text
        self.label_names = label_names or []
        self._data: dict[tuple, float] = {}
        self._lock = threading.Lock()

    def inc(self, labels: dict[str, str] | None = None, value: float = 1):
        label_tuple = self._to_tuple(labels)
        with self._lock:
            self._data[label_tuple] = self._data.get(label_tuple, 0) + value

    def get(self, labels: dict[str, str] | None = None) -> float:
        label_tuple = self._to_tuple(labels)
        with self._lock:
            return self._data.get(label_tuple, 0)

    def _to_tuple(self, labels: dict[str, str] | None) -> tuple:
        if not labels:
            return ()
        return tuple(labels.get(k, "") for k in self.label_names)

    def collect(self) -> list[str]:
        lines = []
        lines.append(f"# HELP {self.name} {self.help}")
        lines.append(f"# TYPE {self.name} counter")
        with self._lock:
            for label_tuple, value in sorted(self._data.items()):
                label_str = self._format_labels(label_tuple)
                lines.append(f"{self.name}{{{label_str}}} {value}")
        return lines

    def _format_labels(self, label_tuple: tuple) -> str:
        if not self.label_names:
            return ""
        parts = []
        for k, v in zip(self.label_names, label_tuple, strict=False):
            v_escaped = str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
            parts.append(f'{k}="{v_escaped}"')
        return ",".join(parts)


class _Gauge:
    """仪表盘"""

    def __init__(self, name: str, help_text: str, label_names: list[str] | None = None):
        self.name = name
        self.help = help_text
        self.label_names = label_names or []
        self._data: dict[tuple, float] = {}
        self._lock = threading.Lock()

    def set(self, value: float, labels: dict[str, str] | None = None):
        label_tuple = self._to_tuple(labels)
        with self._lock:
            self._data[label_tuple] = value

    def inc(self, labels: dict[str, str] | None = None, value: float = 1):
        label_tuple = self._to_tuple(labels)
        with self._lock:
            self._data[label_tuple] = self._data.get(label_tuple, 0) + value

    def dec(self, labels: dict[str, str] | None = None, value: float = 1):
        label_tuple = self._to_tuple(labels)
        with self._lock:
            self._data[label_tuple] = self._data.get(label_tuple, 0) - value

    def get(self, labels: dict[str, str] | None = None) -> float:
        label_tuple = self._to_tuple(labels)
        with self._lock:
            return self._data.get(label_tuple, 0)

    def _to_tuple(self, labels: dict[str, str] | None) -> tuple:
        if not labels:
            return ()
        return tuple(labels.get(k, "") for k in self.label_names)

    def collect(self) -> list[str]:
        lines = []
        lines.append(f"# HELP {self.name} {self.help}")
        lines.append(f"# TYPE {self.name} gauge")
        with self._lock:
            for label_tuple, value in sorted(self._data.items()):
                label_str = self._format_labels(label_tuple)
                lines.append(f"{self.name}{{{label_str}}} {value}")
        return lines

    def _format_labels(self, label_tuple: tuple) -> str:
        if not self.label_names:
            return ""
        parts = []
        for k, v in zip(self.label_names, label_tuple, strict=False):
            v_escaped = str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
            parts.append(f'{k}="{v_escaped}"')
        return ",".join(parts)


class _Histogram:
    """直方图"""

    DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)

    def __init__(
        self, name: str, help_text: str, label_names: list[str] | None = None, buckets: tuple[float, ...] | None = None
    ):
        self.name = name
        self.help = help_text
        self.label_names = label_names or []
        self.buckets = buckets or self.DEFAULT_BUCKETS
        self._buckets: dict[tuple, dict[float, float]] = {}
        self._sums: dict[tuple, float] = {}
        self._counts: dict[tuple, float] = {}
        self._lock = threading.Lock()

    def observe(self, value: float, labels: dict[str, str] | None = None):
        label_tuple = self._to_tuple(labels)
        with self._lock:
            if label_tuple not in self._buckets:
                self._buckets[label_tuple] = {b: 0 for b in self.buckets}
                self._sums[label_tuple] = 0
                self._counts[label_tuple] = 0

            for b in self.buckets:
                if value <= b:
                    self._buckets[label_tuple][b] += 1

            self._sums[label_tuple] += value
            self._counts[label_tuple] += 1

    def _to_tuple(self, labels: dict[str, str] | None) -> tuple:
        if not labels:
            return ()
        return tuple(labels.get(k, "") for k in self.label_names)

    def collect(self) -> list[str]:
        lines = []
        lines.append(f"# HELP {self.name} {self.help}")
        lines.append(f"# TYPE {self.name} histogram")
        with self._lock:
            for label_tuple in sorted(self._buckets):
                label_str = self._format_labels(label_tuple)
                for bucket in sorted(self.buckets):
                    bucket_value = self._buckets[label_tuple].get(bucket, 0)
                    lines.append(f'{self.name}_bucket{{{label_str},le="{bucket}"}} {bucket_value}')
                inf_count = self._counts.get(label_tuple, 0)
                lines.append(f'{self.name}_bucket{{{label_str},le="+Inf"}} {inf_count}')
                lines.append(f"{self.name}_count{{{label_str}}} {inf_count}")
                lines.append(f"{self.name}_sum{{{label_str}}} {self._sums.get(label_tuple, 0)}")
        return lines

    def _format_labels(self, label_tuple: tuple) -> str:
        if not self.label_names:
            return ""
        parts = []
        for k, v in zip(self.label_names, label_tuple, strict=False):
            v_escaped = str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
            parts.append(f'{k}="{v_escaped}"')
        return ",".join(parts)


class MetricsCollector:
    """轻量级指标收集器"""

    def __init__(self):
        self.request_total = _Counter(
            "request_total",
            "Total number of HTTP requests",
            ["method", "endpoint", "status"],
        )
        self.request_duration_seconds = _Histogram(
            "request_duration_seconds",
            "HTTP request duration in seconds",
            ["method", "endpoint"],
        )
        self.conversion_total = _Counter(
            "conversion_total",
            "Total number of conversions",
            ["file_type", "status"],
        )
        self.conversion_duration_seconds = _Histogram(
            "conversion_duration_seconds",
            "Conversion duration in seconds",
            ["file_type"],
        )
        self.file_size_bytes = _Histogram(
            "file_size_bytes",
            "Input file size distribution in bytes",
            ["file_type"],
            buckets=(1024, 10240, 102400, 1048576, 10485760, 52428800, 104857600),
        )
        self.cache_hits_total = _Counter(
            "cache_hits_total",
            "Total number of cache hits",
        )
        self.active_conversions = _Gauge(
            "active_conversions",
            "Number of currently active conversions",
        )
        self.errors_total = _Counter(
            "errors_total",
            "Total number of errors",
            ["type"],
        )

    def record_request(self, method: str, endpoint: str, status: int, duration: float):
        """记录 HTTP 请求指标"""
        self.request_total.inc({"method": method, "endpoint": endpoint, "status": str(status)})
        self.request_duration_seconds.observe(duration, {"method": method, "endpoint": endpoint})

    def record_conversion(self, file_type: str, status: str, duration: float, file_size: int = 0):
        """记录转换指标"""
        self.conversion_total.inc({"file_type": file_type, "status": status})
        self.conversion_duration_seconds.observe(duration, {"file_type": file_type})
        if file_size > 0:
            self.file_size_bytes.observe(float(file_size), {"file_type": file_type})

    def record_cache_hit(self):
        """记录缓存命中"""
        self.cache_hits_total.inc()

    def record_error(self, error_type: str):
        """记录错误"""
        self.errors_total.inc({"type": error_type})

    def export_prometheus(self) -> str:
        """以 Prometheus 文本格式导出所有指标"""
        collectors = [
            self.request_total,
            self.request_duration_seconds,
            self.conversion_total,
            self.conversion_duration_seconds,
            self.file_size_bytes,
            self.cache_hits_total,
            self.active_conversions,
            self.errors_total,
        ]

        parts = []
        for collector in collectors:
            lines = collector.collect()
            if lines:
                parts.append("\n".join(lines))

        result = "\n\n".join(parts)
        if result:
            result += "\n"
        return result


# ==================== 全局实例 ====================

_collector: MetricsCollector | None = None


def get_metrics_collector() -> MetricsCollector:
    """获取全局 MetricsCollector 单例"""
    global _collector
    if _collector is None:
        _collector = MetricsCollector()
    return _collector


class MetricsMiddleware:
    """ASGI 中间件，用于收集 HTTP 指标（纯 ASGI 实现）"""

    def __init__(self, app, collector: MetricsCollector):
        self.app = app
        self.collector = collector

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start_time = time.time()
        response_status = [500]  # 默认状态码
        endpoint = scope.get("path", "/")
        method = scope.get("method", "UNKNOWN")

        async def wrapped_send(message):
            if message["type"] == "http.response.start":
                response_status[0] = message.get("status", 500)
            await send(message)

        try:
            await self.app(scope, receive, wrapped_send)
        except Exception:
            response_status[0] = 500
            raise
        finally:
            duration = time.time() - start_time
            self.collector.record_request(
                method=method,
                endpoint=endpoint,
                status=response_status[0],
                duration=duration,
            )
