"""Loki log collector."""
import logging
import time
from typing import Optional

import requests

from .config import LOKI_URL, QUERY_TIMEOUT, TARGET_NAMESPACE

logger = logging.getLogger(__name__)


class LokiCollector:
    """Collect logs from Loki for RCA analysis."""

    def __init__(self, base_url: str = LOKI_URL):
        self.base_url = base_url.rstrip("/")

    def _query(
        self,
        logql: str,
        start_ns: int,
        end_ns: int,
        limit: int = 200,
    ) -> list[dict]:
        """Execute LogQL query."""
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
            if data["status"] != "success":
                logger.warning("Loki query failed: %s", data.get("error", ""))
                return []

            entries = []
            for stream in data["data"]["result"]:
                labels = stream.get("stream", {})
                for ts, line in stream.get("values", []):
                    entries.append({
                        "timestamp": ts,
                        "labels": labels,
                        "line": line,
                    })
            return entries
        except Exception as e:
            logger.error("Loki query error: %s (query: %s)", e, logql)
            return []

    def collect(
        self,
        namespace: str = TARGET_NAMESPACE,
        window_minutes: int = 5,
        error_only: bool = False,
    ) -> dict:
        """Collect relevant logs for RCA."""
        now_ns = int(time.time() * 1e9)
        start_ns = now_ns - int(window_minutes * 60 * 1e9)

        return {
            "pod_logs": self._collect_pod_logs(
                namespace, start_ns, now_ns, error_only
            ),
            "k8s_events": self._collect_events(namespace, start_ns, now_ns),
        }

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
