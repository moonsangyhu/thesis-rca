"""Loki log collector."""
import logging
import time
from collections.abc import Callable

import requests

from .config import LOKI_URL, QUERY_TIMEOUT, TARGET_NAMESPACE

logger = logging.getLogger(__name__)


class LokiQueryError(RuntimeError):
    """Raised when a Loki query cannot be proven successful."""


class LokiCollector:
    """Collect logs from Loki for RCA analysis."""

    def __init__(
        self,
        base_url: str = LOKI_URL,
        *,
        recover_query_path: Callable[[], bool] | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self._recover_query_path = recover_query_path

    def _recover_once(self) -> bool:
        if self._recover_query_path is not None:
            return self._recover_query_path() is True
        # Keep the generic collector importable in offline tests.  The live
        # experiment owns this bounded local port-forward repair path.
        from experiments.shared.infra import _restart_port_forward
        return _restart_port_forward("monitoring", "loki", 3100)

    def _query(
        self,
        logql: str,
        start_ns: int,
        end_ns: int,
        limit: int = 200,
    ) -> list[dict]:
        """Execute LogQL query."""
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                resp = requests.get(
                    f"{self.base_url}/loki/api/v1/query_range",
                    params={
                        "query": logql,
                        "start": start_ns,
                        "end": end_ns,
                        "limit": limit,
                    },
                    timeout=QUERY_TIMEOUT,
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("status") != "success":
                    raise LokiQueryError(
                        f"Loki returned non-success status: {data.get('error', '')}"
                    )
                result = data.get("data", {}).get("result")
                if not isinstance(result, list):
                    raise LokiQueryError("Loki success response has invalid result schema")

                entries = []
                for stream in result:
                    labels = stream.get("stream", {})
                    for ts, line in stream.get("values", []):
                        entries.append({
                            "timestamp": ts,
                            "labels": labels,
                            "line": line,
                        })
                return entries
            except Exception as exc:
                last_error = exc
                logger.error(
                    "Loki query attempt %d/2 failed: %s (query: %s)",
                    attempt + 1, exc, logql,
                )
                if attempt == 0:
                    try:
                        if self._recover_once():
                            continue
                    except Exception as recovery_error:
                        last_error = recovery_error
                break
        raise LokiQueryError("Loki query failed after bounded recovery") from last_error

    def collect(
        self,
        namespace: str = TARGET_NAMESPACE,
        window_minutes: int = 5,
        error_only: bool = False,
    ) -> dict:
        """Collect relevant logs for RCA."""
        now_ns = int(time.time() * 1e9)
        start_ns = now_ns - int(window_minutes * 60 * 1e9)

        result = {
            "pod_logs": self._collect_pod_logs(
                namespace, start_ns, now_ns, error_only
            ),
            "k8s_events": self._collect_events(namespace, start_ns, now_ns),
        }
        result["query_status"] = {
            "pod_logs": "success",
            "k8s_events": "success",
        }
        return result

    def _collect_pod_logs(
        self,
        ns: str,
        start_ns: int,
        end_ns: int,
        error_only: bool,
    ) -> list[dict]:
        """Collect pod logs, optionally filtered to errors."""
        if error_only:
            query = (
                f'{{namespace="{ns}"}}'
                f' |~ "(?i)(error|fatal|panic|exception|fail|crash|oom|killed|refused|timeout)"'
            )
        else:
            query = f'{{namespace="{ns}"}}'

        entries = self._query(query, start_ns, end_ns, limit=500)

        # Deduplicate and format
        seen = set()
        results = []
        for entry in entries:
            key = (entry["labels"].get("pod", ""), entry["line"][:100])
            if key in seen:
                continue
            seen.add(key)
            results.append({
                "pod": entry["labels"].get("pod", ""),
                "container": entry["labels"].get("container", ""),
                "line": entry["line"],
            })

        return results[:200]  # cap output

    def _collect_events(
        self,
        ns: str,
        start_ns: int,
        end_ns: int,
    ) -> list[dict]:
        """Collect Kubernetes events from Loki (if event-exporter is running)."""
        query = (
            f'{{job="kubernetes-events"}}'
            f' |~ "{ns}"'
            f' |~ "(?i)(warning|error|failed|backoff|oom|evict|unhealthy|kill)"'
        )
        entries = self._query(query, start_ns, end_ns, limit=100)
        return [
            {
                "line": entry["line"],
            }
            for entry in entries
        ]

    def collect_error_summary(
        self,
        namespace: str = TARGET_NAMESPACE,
        window_minutes: int = 5,
    ) -> list[dict]:
        """Collect only error/warning logs - concise for LLM context."""
        return self.collect(
            namespace=namespace,
            window_minutes=window_minutes,
            error_only=True,
        )["pod_logs"]
