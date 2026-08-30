import unittest
from unittest.mock import MagicMock, patch

import requests

from src.collector.loki import LokiCollector, LokiQueryError


def success_response(result=None):
    response = MagicMock(status_code=200)
    response.json.return_value = {
        "status": "success",
        "data": {"result": [] if result is None else result},
    }
    return response


class LokiCollectorTests(unittest.TestCase):
    def test_timeout_repairs_port_forward_once_then_records_query_success(self):
        recover = MagicMock(return_value=True)
        collector = LokiCollector(recover_query_path=recover)
        with patch("src.collector.loki.requests.get", side_effect=(
            requests.Timeout("stalled"), success_response(), success_response(),
        )) as request:
            result = collector.collect(error_only=True)

        self.assertEqual(result["pod_logs"], [])
        self.assertEqual(result["k8s_events"], [])
        self.assertEqual(result["query_status"], {
            "pod_logs": "success", "k8s_events": "success",
        })
        recover.assert_called_once_with()
        self.assertEqual(request.call_count, 3)

    def test_second_failure_is_not_converted_to_empty_logs(self):
        recover = MagicMock(return_value=True)
        collector = LokiCollector(recover_query_path=recover)
        with patch(
            "src.collector.loki.requests.get",
            side_effect=(requests.Timeout("first"), requests.Timeout("second")),
        ), self.assertRaisesRegex(LokiQueryError, "bounded recovery"):
            collector.collect(error_only=True)

        recover.assert_called_once_with()

    def test_non_success_response_is_fail_closed(self):
        response = success_response()
        response.json.return_value = {"status": "error", "error": "backend busy"}
        collector = LokiCollector(recover_query_path=lambda: False)
        with patch("src.collector.loki.requests.get", return_value=response), \
                self.assertRaises(LokiQueryError):
            collector.collect(error_only=True)


if __name__ == "__main__":
    unittest.main()
