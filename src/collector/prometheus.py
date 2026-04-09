"""Prometheus metrics collector."""
import logging
import time
from typing import Optional

import requests

from .config import PROMETHEUS_URL, QUERY_TIMEOUT, TARGET_NAMESPACE

logger = logging.getLogger(__name__)


class PrometheusCollector:
    """Collect metrics from Prometheus for RCA analysis."""

    def __init__(self, base_url: str = PROMETHEUS_URL):
        self.base_url = base_url.rstrip("/")

    def _query(self, promql: str) -> list[dict]:
        """Execute instant query."""
        try:
            resp = requests.get(
                f"{self.base_url}/api/v1/query",
                params={"query": promql},
                timeout=QUERY_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            if data["status"] != "success":
                logger.warning("Prometheus query failed: %s", data.get("error", ""))
                return []
            return data["data"]["result"]
        except Exception as e:
            logger.error("Prometheus query error: %s (query: %s)", e, promql)
            return []

    def _query_range(
        self, promql: str, start: float, end: float, step: str = "15s"
    ) -> list[dict]:
        """Execute range query."""
        try:
            resp = requests.get(
                f"{self.base_url}/api/v1/query_range",
                params={
                    "query": promql,
                    "start": start,
                    "end": end,
                    "step": step,
                },
                timeout=QUERY_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            if data["status"] != "success":
                return []
            return data["data"]["result"]
        except Exception as e:
            logger.error("Prometheus range query error: %s", e)
            return []

    def collect(
        self,
        namespace: str = TARGET_NAMESPACE,
        window_minutes: int = 5,
    ) -> dict:
        """Collect all relevant metrics for RCA."""
        now = time.time()
        start = now - (window_minutes * 60)

        return {
            "pod_status": self._collect_pod_status(namespace),
            "container_restarts": self._collect_restarts(namespace),
            "oom_events": self._collect_oom(namespace),
            "cpu_throttling": self._collect_cpu_throttle(namespace, start, now),
            "memory_usage": self._collect_memory(namespace),
            "node_status": self._collect_node_status(),
            "endpoint_status": self._collect_endpoints(namespace),
            "pvc_status": self._collect_pvc(namespace),
            "resource_quota": self._collect_quota(namespace),
            "network_drops": self._collect_network_drops(namespace),
            "request_latency": self._collect_request_latency(namespace),
            "grpc_errors": self._collect_grpc_errors(namespace),
            "network_errors": self._collect_network_errors(),
            "tcp_retransmissions": self._collect_tcp_retrans(),
        }

    def _collect_pod_status(self, ns: str) -> list[dict]:
        """Pod phase and container status."""
        results = []
        # Pod phase
        for phase in ["Pending", "Running", "Failed", "Unknown"]:
            data = self._query(
                f'kube_pod_status_phase{{namespace="{ns}",phase="{phase}"}} == 1'
            )
            for item in data:
                results.append({
                    "pod": item["metric"].get("pod", ""),
                    "phase": phase,
                })

        # Container waiting reasons
        for reason in [
            "CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull",
            "CreateContainerConfigError", "ContainerCreating",
        ]:
            data = self._query(
                f'kube_pod_container_status_waiting_reason'
                f'{{namespace="{ns}",reason="{reason}"}} == 1'
            )
            for item in data:
                results.append({
                    "pod": item["metric"].get("pod", ""),
                    "container": item["metric"].get("container", ""),
                    "waiting_reason": reason,
                })

        # Terminated reasons
        for reason in ["OOMKilled", "Error", "Completed"]:
            data = self._query(
                f'kube_pod_container_status_last_terminated_reason'
                f'{{namespace="{ns}",reason="{reason}"}} == 1'
            )
            for item in data:
                results.append({
                    "pod": item["metric"].get("pod", ""),
                    "container": item["metric"].get("container", ""),
                    "terminated_reason": reason,
                })

        return results

    def _collect_restarts(self, ns: str) -> list[dict]:
        """Container restart counts."""
        data = self._query(
            f'kube_pod_container_status_restarts_total{{namespace="{ns}"}} > 0'
        )
        return [
            {
                "pod": item["metric"].get("pod", ""),
                "container": item["metric"].get("container", ""),
                "restarts": int(float(item["value"][1])),
            }
            for item in data
        ]

    def _collect_oom(self, ns: str) -> list[dict]:
        """OOMKilled events from metrics."""
        data = self._query(
            f'kube_pod_container_status_last_terminated_reason'
            f'{{namespace="{ns}",reason="OOMKilled"}} == 1'
        )
        return [
            {
                "pod": item["metric"].get("pod", ""),
                "container": item["metric"].get("container", ""),
            }
            for item in data
        ]

    def _collect_cpu_throttle(
        self, ns: str, start: float, end: float
    ) -> list[dict]:
        """CPU throttling ratio."""
        data = self._query(
            f'rate(container_cpu_cfs_throttled_periods_total'
            f'{{namespace="{ns}"}}[5m])'
            f' / rate(container_cpu_cfs_periods_total'
            f'{{namespace="{ns}"}}[5m]) > 0.1'
        )
        return [
            {
                "pod": item["metric"].get("pod", ""),
                "container": item["metric"].get("container", ""),
                "throttle_ratio": round(float(item["value"][1]), 3),
            }
            for item in data
        ]

    def _collect_memory(self, ns: str) -> list[dict]:
        """Memory usage vs limits."""
        data = self._query(
            f'container_memory_working_set_bytes{{namespace="{ns}",container!=""}}'
            f' / on(namespace,pod,container) group_left()'
            f' kube_pod_container_resource_limits{{namespace="{ns}",resource="memory"}} > 0.8'
        )
        return [
            {
                "pod": item["metric"].get("pod", ""),
                "container": item["metric"].get("container", ""),
                "memory_usage_ratio": round(float(item["value"][1]), 3),
            }
            for item in data
        ]

    def _collect_node_status(self) -> list[dict]:
        """Node conditions."""
        results = []
        for condition in ["Ready", "MemoryPressure", "DiskPressure", "NetworkUnavailable"]:
            expected = "true" if condition == "Ready" else "false"
            # Find nodes where condition deviates from expected
            if condition == "Ready":
                data = self._query(
                    f'kube_node_status_condition{{condition="{condition}",status="true"}} == 0'
                )
            else:
                data = self._query(
                    f'kube_node_status_condition{{condition="{condition}",status="true"}} == 1'
                )
            for item in data:
                results.append({
                    "node": item["metric"].get("node", ""),
                    "condition": condition,
                    "status": "unhealthy",
                })
        return results

    def _collect_endpoints(self, ns: str) -> list[dict]:
        """Service endpoint availability."""
        data = self._query(
            f'kube_endpoint_address_available{{namespace="{ns}"}} == 0'
        )
        return [
            {
                "endpoint": item["metric"].get("endpoint", ""),
                "available": 0,
            }
            for item in data
        ]

    def _collect_pvc(self, ns: str) -> list[dict]:
        """PVC status."""
        results = []
        for phase in ["Pending", "Lost"]:
            data = self._query(
                f'kube_persistentvolumeclaim_status_phase'
                f'{{namespace="{ns}",phase="{phase}"}} == 1'
            )
            for item in data:
                results.append({
                    "pvc": item["metric"].get("persistentvolumeclaim", ""),
                    "phase": phase,
                })
        return results

    def _collect_quota(self, ns: str) -> list[dict]:
        """ResourceQuota usage."""
        data = self._query(
            f'kube_resourcequota{{namespace="{ns}",type="used"}}'
            f' / on(namespace,resourcequota,resource) '
            f'kube_resourcequota{{namespace="{ns}",type="hard"}} > 0.9'
        )
        return [
            {
                "resource": item["metric"].get("resource", ""),
                "usage_ratio": round(float(item["value"][1]), 3),
            }
            for item in data
        ]

    def _collect_network_drops(self, ns: str) -> list[dict]:
        """Cilium/CNI network policy drops."""
        data = self._query(
            'rate(cilium_drop_count_total[2m]) > 0'
        )
        return [
            {
                "reason": item["metric"].get("reason", ""),
                "direction": item["metric"].get("direction", ""),
                "rate": round(float(item["value"][1]), 3),
            }
            for item in data
        ]

    def _collect_request_latency(self, ns: str) -> list[dict]:
        """gRPC/HTTP request latency p95."""
        data = self._query(
            'histogram_quantile(0.95, sum(rate(grpc_server_handling_seconds_bucket{grpc_service=~".*",job=~".*"}[2m])) by (le, grpc_service, grpc_method))'
        )
        results = []
        for item in data:
            val = float(item["value"][1])
            if val > 0.5:  # p95 > 500ms
                results.append({
                    "service": item["metric"].get("grpc_service", "unknown"),
                    "method": item["metric"].get("grpc_method", ""),
                    "p95_seconds": round(val, 3),
                })
        return results

    def _collect_grpc_errors(self, ns: str) -> list[dict]:
        """gRPC non-OK error rates."""
        data = self._query(
            'sum(rate(grpc_server_handled_total{grpc_code!="OK",job=~".*"}[2m])) by (grpc_service, grpc_code) > 0'
        )
        return [
            {
                "service": item["metric"].get("grpc_service", "unknown"),
                "code": item["metric"].get("grpc_code", ""),
                "rate": round(float(item["value"][1]), 4),
            }
            for item in data
        ]

    def _collect_network_errors(self) -> list[dict]:
        """Node-level network transmit/receive errors."""
        results = []
        for metric in ["node_network_transmit_errs_total", "node_network_receive_errs_total"]:
            data = self._query(f'rate({metric}{{device!~"lo|veth.*|cali.*|cilium.*"}}[2m]) > 0')
            for item in data:
                results.append({
                    "node": item["metric"].get("instance", "unknown"),
                    "device": item["metric"].get("device", ""),
                    "type": "transmit_err" if "transmit" in metric else "receive_err",
                    "rate": round(float(item["value"][1]), 4),
                })
        return results

    def _collect_tcp_retrans(self) -> list[dict]:
        """TCP retransmission rate per node."""
        data = self._query('rate(node_netstat_Tcp_RetransSegs[2m]) > 1.0')
        results = []
        for item in data:
            val = float(item["value"][1])
            if val > 1.0:  # filter trivial retransmissions
                results.append({
                    "node": item["metric"].get("instance", "unknown"),
                    "retrans_rate": round(val, 2),
                })
        return results
