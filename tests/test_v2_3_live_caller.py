import json
import unittest
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import call, patch

from experiments.shared.copilot_cli import (
    RETRYABLE_MALFORMED_JSONL_FAILURE_CODE,
    RETRYABLE_QUOTA_NULL_AUTH_FAILURE_CODE,
    RETRYABLE_ZERO_USAGE_AUTH_FAILURE_CODE,
    CopilotCLIError,
    CopilotCLIResponse,
)
from experiments.v2_3.conditions import ConditionAssembler
from experiments.v2_3.engine import RCAEngineV2_3
from experiments.v2_3.live_caller import AuthorizedTerraCaller, LiveCallerError
from experiments.v2_3.mock import clean_fixture
from tests.v2_3_helpers import LIVE_ENV, verified_authorization


class FakeBackend:
    model = "gpt-5.6-terra"
    max_ai_credits = 0.1

    def __init__(self):
        self.calls = []
        self.receipts = []
        self.charge_observer = self.receipts.append

    def _billing_guard_passes(self):
        return True

    def call(self, prompt, system_prompt, max_tokens):
        self.calls.append((prompt, system_prompt, max_tokens))
        index = len(self.calls)
        self.charge_observer({"attempt_id": f"attempt-{index}"})
        if "blinded correctness judge" in system_prompt:
            text = json.dumps({"correctness_score": 0.75})
            output_tokens = 7
        else:
            text = json.dumps({
                "identified_fault_type": "latency anomaly",
                "root_cause": "sealed mock diagnosis",
                "remediation": ["inspect frozen evidence"],
            })
            output_tokens = 30
        now = datetime.now(timezone.utc).isoformat()
        return CopilotCLIResponse(
            text=text,
            model=self.model,
            session_id=f"live-mock-{index}",
            output_tokens=output_tokens,
            ai_credits=0.1,
            premium_requests=1.0,
            started_at=now,
            ended_at=now,
            latency_ms=1,
            cli_executable="/opt/bin/copilot",
            temporary_cwd_id=f"isolated-{index}",
        )


class MalformedBackend(FakeBackend):
    def call(self, prompt, system_prompt, max_tokens):
        response = super().call(prompt, system_prompt, max_tokens)
        return CopilotCLIResponse(**{**response.__dict__, "text": "not-json"})


class StrictParseFailureBackend(FakeBackend):
    def call(self, prompt, system_prompt, max_tokens):
        self.calls.append((prompt, system_prompt, max_tokens))
        receipt = {"attempt_id": "strict-failure", "ai_credits": 9.0}
        self.charge_observer(receipt)
        raise CopilotCLIError("strict JSONL parse failed", receipt)


class RetryableMalformedJsonlBackend(FakeBackend):
    def call(self, prompt, system_prompt, max_tokens):
        if not self.calls:
            self.calls.append((prompt, system_prompt, max_tokens))
            receipt = {"attempt_id": "truncated", "ai_credits": 0.2,
                       "premium_requests": 1.0, "usage_metadata_complete": True,
                       "actual_model": self.model, "output_tokens": 5}
            self.charge_observer(receipt)
            raise CopilotCLIError("Copilot SDK emitted malformed JSONL", receipt,
                                  failure_code=RETRYABLE_MALFORMED_JSONL_FAILURE_CODE)
        return super().call(prompt, system_prompt, max_tokens)


class RetryableMetadataBackend(FakeBackend):
    def __init__(self, fail_twice=False):
        super().__init__()
        self.fail_twice = fail_twice

    def call(self, prompt, system_prompt, max_tokens):
        if len(self.calls) == 0 or (self.fail_twice and len(self.calls) == 1):
            self.calls.append((prompt, system_prompt, max_tokens))
            index = len(self.calls)
            receipt = {
                "attempt_id": f"metadata-{index}",
                "ai_credits": 0.2,
                "premium_requests": 1.0,
                "usage_metadata_complete": True,
                "actual_model": self.model,
                "output_tokens": 5,
            }
            self.charge_observer(receipt)
            raise CopilotCLIError(
                "Copilot skills metadata entry is invalid: path_type",
                receipt,
                retryable_control_metadata=True,
                failure_code="path_type",
            )
        return super().call(prompt, system_prompt, max_tokens)


class RetryableZeroUsageAuthBackend(FakeBackend):
    def __init__(self, fail_twice=False, malformed_receipt=False):
        super().__init__()
        self.fail_twice = fail_twice
        self.malformed_receipt = malformed_receipt

    def call(self, prompt, system_prompt, max_tokens):
        if len(self.calls) == 0 or (self.fail_twice and len(self.calls) == 1):
            self.calls.append((prompt, system_prompt, max_tokens))
            index = len(self.calls)
            receipt = {
                "attempt_id": f"auth-{index}",
                "ai_credits": 0.0,
                "premium_requests": 0.0,
                "usage_metadata_complete": True,
                "actual_model": None,
                "output_tokens": 1 if self.malformed_receipt else 0,
            }
            self.charge_observer(receipt)
            raise CopilotCLIError(
                "sealed zero-usage authentication failure",
                receipt,
                retryable_zero_usage_authentication=True,
                failure_code=RETRYABLE_ZERO_USAGE_AUTH_FAILURE_CODE,
            )
        return super().call(prompt, system_prompt, max_tokens)


class RetryableQuotaNullAuthBackend(RetryableZeroUsageAuthBackend):
    def call(self, prompt, system_prompt, max_tokens):
        if len(self.calls) == 0 or (self.fail_twice and len(self.calls) == 1):
            self.calls.append((prompt, system_prompt, max_tokens))
            receipt = {
                "attempt_id": "quota-null-auth", "ai_credits": 0.0,
                "premium_requests": 0.0, "usage_metadata_complete": True,
                "actual_model": None, "output_tokens": 0,
            }
            self.charge_observer(receipt)
            raise CopilotCLIError(
                "sealed quota-null pre-session failure", receipt,
                retryable_zero_usage_authentication=True,
                failure_code=RETRYABLE_QUOTA_NULL_AUTH_FAILURE_CODE,
            )
        return FakeBackend.call(self, prompt, system_prompt, max_tokens)


class LiveCallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict("os.environ", LIVE_ENV, clear=False)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def authorization(self):
        return verified_authorization(Path(self.temp.name))

    def test_engine_uses_authorized_terra_caller_with_complete_ledger(self):
        runtime, procedure, lexicon = clean_fixture("F1", 1)
        context = ConditionAssembler().assemble_all(runtime, procedure, lexicon)["runtime"]
        backend = FakeBackend()
        caller = AuthorizedTerraCaller(
            self.authorization(), backend, "pilot-campaign", "copilot-1.0.78"
        )
        engine = RCAEngineV2_3(caller, campaign_id="pilot-campaign")
        row = engine.analyze_condition(
            context, "F1", 1, judge_reference="sealed expected RCA"
        )
        self.assertEqual(row["representative_score"], 0.75)
        self.assertEqual(len(engine.ledger.entries), 12)
        self.assertAlmostEqual(caller.cumulative_aic, 1.2)
        self.assertEqual(len({entry.session_id for entry in engine.ledger.entries}), 12)
        for entry in engine.ledger.entries:
            entry.validate()
            self.assertEqual(entry.actual_model, "gpt-5.6-terra")
            self.assertEqual(entry.provider, "copilot")
        judge_prompts = [prompt for prompt, system, _ in backend.calls
                         if "blinded correctness judge" in system]
        self.assertEqual(len(judge_prompts), 9)
        self.assertTrue(all("sealed expected RCA" in prompt for prompt in judge_prompts))
        self.assertTrue(all("blind_procedural_rag" not in prompt for prompt in judge_prompts))

    def test_explicit_unbounded_campaign_keeps_session_guard(self):
        backend = FakeBackend()
        backend.max_ai_credits = 30
        caller = AuthorizedTerraCaller(
            self.authorization(), backend, "main-campaign", "copilot-1.0.78",
            max_campaign_aic=None,
        )
        caller.cumulative_aic = 10_000
        self.assertIsNone(caller.max_campaign_aic)
        self.assertEqual(backend.max_ai_credits, 30)

    def test_campaign_aic_cap_blocks_before_next_call(self):
        backend = FakeBackend()
        caller = AuthorizedTerraCaller(
            self.authorization(), backend, "pilot-campaign", "copilot-1.0.78",
            max_campaign_aic=0.1,
        )
        runtime, procedure, lexicon = clean_fixture("F1", 1)
        context = ConditionAssembler().assemble_all(runtime, procedure, lexicon)["runtime"]
        from experiments.v2_3.engine import Invocation
        invocation = Invocation("generator", "F1", 1, "runtime", 1, None,
                                context.full_context, context)
        caller(invocation)
        with self.assertRaisesRegex(LiveCallerError, "cap reached"):
            caller(invocation)
        self.assertEqual(len(backend.calls), 1)

    def test_session_ceiling_is_reserved_before_subprocess(self):
        backend = FakeBackend()
        backend.max_ai_credits = 30
        caller = AuthorizedTerraCaller(
            self.authorization(), backend, "pilot-campaign", "copilot-1.0.78",
            max_campaign_aic=360,
        )
        caller.cumulative_aic = 331
        runtime, procedure, lexicon = clean_fixture("F1", 1)
        context = ConditionAssembler().assemble_all(runtime, procedure, lexicon)["runtime"]
        from experiments.v2_3.engine import Invocation
        invocation = Invocation(
            "generator", "F1", 1, "runtime", 1, None,
            context.full_context, context,
        )

        with self.assertRaisesRegex(LiveCallerError, "cap reached before call"):
            caller(invocation)

        self.assertEqual(backend.calls, [])

    def test_charged_malformed_response_updates_usage_before_parse_failure(self):
        backend = MalformedBackend()
        caller = AuthorizedTerraCaller(
            self.authorization(), backend, "pilot-campaign", "copilot-1.0.78"
        )
        runtime, procedure, lexicon = clean_fixture("F1", 1)
        context = ConditionAssembler().assemble_all(runtime, procedure, lexicon)["runtime"]
        from experiments.v2_3.engine import Invocation
        invocation = Invocation(
            "generator", "F1", 1, "runtime", 1, None,
            context.full_context, context,
        )
        with self.assertRaisesRegex(LiveCallerError, "valid JSON"):
            caller(invocation)
        self.assertEqual(len(backend.receipts), 1)
        self.assertAlmostEqual(caller.cumulative_aic, 0.1)

    def test_complete_charged_truncated_jsonl_retries_once(self):
        backend = RetryableMalformedJsonlBackend()
        caller = AuthorizedTerraCaller(self.authorization(), backend, "pilot-campaign", "copilot-1.0.78")
        runtime, procedure, lexicon = clean_fixture("F1", 1)
        context = ConditionAssembler().assemble_all(runtime, procedure, lexicon)["runtime"]
        from experiments.v2_3.engine import Invocation
        caller(Invocation("generator", "F1", 1, "runtime", 1, None,
                          context.full_context, context))
        self.assertEqual(len(backend.calls), 2)
        self.assertAlmostEqual(caller.cumulative_aic, 0.3)

    def test_charged_cap_exceed_updates_usage_before_failure(self):
        backend = FakeBackend()
        backend.max_ai_credits = 0.05
        caller = AuthorizedTerraCaller(
            self.authorization(), backend, "pilot-campaign", "copilot-1.0.78",
            max_campaign_aic=0.05,
        )
        runtime, procedure, lexicon = clean_fixture("F1", 1)
        context = ConditionAssembler().assemble_all(runtime, procedure, lexicon)["runtime"]
        from experiments.v2_3.engine import Invocation
        invocation = Invocation(
            "generator", "F1", 1, "runtime", 1, None,
            context.full_context, context,
        )
        with self.assertRaisesRegex(LiveCallerError, "cap exceeded"):
            caller(invocation)
        self.assertEqual(len(backend.receipts), 1)
        self.assertAlmostEqual(caller.cumulative_aic, 0.1)

    def test_backend_strict_parse_failure_updates_campaign_aic(self):
        backend = StrictParseFailureBackend()
        caller = AuthorizedTerraCaller(
            self.authorization(), backend, "pilot-campaign", "copilot-1.0.78"
        )
        runtime, procedure, lexicon = clean_fixture("F1", 1)
        context = ConditionAssembler().assemble_all(runtime, procedure, lexicon)["runtime"]
        from experiments.v2_3.engine import Invocation
        invocation = Invocation(
            "generator", "F1", 1, "runtime", 1, None,
            context.full_context, context,
        )
        with self.assertRaisesRegex(LiveCallerError, "durable charge receipt"):
            caller(invocation)
        self.assertEqual(len(backend.receipts), 1)
        self.assertEqual(caller.cumulative_aic, 9.0)
        with self.assertRaisesRegex(LiveCallerError, "campaign aborted"):
            caller(invocation)
        self.assertEqual(len(backend.receipts), 1)

    def test_retryable_control_metadata_retries_once_and_aggregates_usage(self):
        backend = RetryableMetadataBackend()
        caller = AuthorizedTerraCaller(
            self.authorization(), backend, "main-campaign", "copilot-1.0.78",
            max_campaign_aic=None,
        )
        runtime, procedure, lexicon = clean_fixture("F1", 1)
        context = ConditionAssembler().assemble_all(runtime, procedure, lexicon)["runtime"]
        from experiments.v2_3.engine import Invocation
        invocation = Invocation(
            "generator", "F1", 1, "runtime", 1, None,
            context.full_context, context,
        )

        result = caller(invocation)

        self.assertEqual(len(backend.calls), 2)
        self.assertEqual(len(backend.receipts), 2)
        self.assertAlmostEqual(caller.cumulative_aic, 0.3)
        self.assertAlmostEqual(result.ledger_entry.ai_credits, 0.3)
        self.assertAlmostEqual(result.ledger_entry.cumulative_ai_credits, 0.3)
        self.assertAlmostEqual(result.ledger_entry.premium_requests, 2.0)

    def test_second_control_metadata_failure_aborts_without_third_call(self):
        backend = RetryableMetadataBackend(fail_twice=True)
        caller = AuthorizedTerraCaller(
            self.authorization(), backend, "main-campaign", "copilot-1.0.78",
            max_campaign_aic=None,
        )
        runtime, procedure, lexicon = clean_fixture("F1", 1)
        context = ConditionAssembler().assemble_all(runtime, procedure, lexicon)["runtime"]
        from experiments.v2_3.engine import Invocation
        invocation = Invocation(
            "generator", "F1", 1, "runtime", 1, None,
            context.full_context, context,
        )

        with self.assertRaisesRegex(LiveCallerError, "durable charge receipt"):
            caller(invocation)

        self.assertEqual(len(backend.calls), 2)
        self.assertEqual(len(backend.receipts), 2)
        self.assertAlmostEqual(caller.cumulative_aic, 0.4)
        self.assertTrue(caller.campaign_aborted)
        with self.assertRaisesRegex(LiveCallerError, "campaign aborted"):
            caller(invocation)
        self.assertEqual(len(backend.receipts), 2)

    def test_zero_usage_auth_failure_retries_once_without_inflating_usage(self):
        backend = RetryableZeroUsageAuthBackend()
        caller = AuthorizedTerraCaller(
            self.authorization(), backend, "main-campaign", "copilot-1.0.78",
            max_campaign_aic=None,
        )
        runtime, procedure, lexicon = clean_fixture("F1", 1)
        context = ConditionAssembler().assemble_all(runtime, procedure, lexicon)["runtime"]
        from experiments.v2_3.engine import Invocation
        invocation = Invocation(
            "generator", "F1", 1, "runtime", 1, None,
            context.full_context, context,
        )

        result = caller(invocation)

        self.assertEqual(len(backend.calls), 2)
        self.assertEqual(len(backend.receipts), 2)
        self.assertAlmostEqual(caller.cumulative_aic, 0.1)
        self.assertAlmostEqual(result.ledger_entry.ai_credits, 0.1)
        self.assertAlmostEqual(result.ledger_entry.premium_requests, 1.0)

    def test_quota_null_pre_session_failure_retries_once_without_usage(self):
        backend = RetryableQuotaNullAuthBackend()
        caller = AuthorizedTerraCaller(
            self.authorization(), backend, "main-campaign", "copilot-1.0.78",
            max_campaign_aic=None,
        )
        runtime, procedure, lexicon = clean_fixture("F1", 1)
        context = ConditionAssembler().assemble_all(runtime, procedure, lexicon)["runtime"]
        from experiments.v2_3.engine import Invocation

        result = caller(Invocation(
            "generator", "F1", 1, "runtime", 1, None,
            context.full_context, context,
        ))

        self.assertEqual(len(backend.calls), 2)
        self.assertEqual(len(backend.receipts), 2)
        self.assertAlmostEqual(caller.cumulative_aic, 0.1)
        self.assertAlmostEqual(result.ledger_entry.ai_credits, 0.1)
        self.assertAlmostEqual(result.ledger_entry.premium_requests, 1.0)

    @patch("experiments.v2_3.live_caller.time.sleep")
    def test_quota_null_pre_session_failure_allows_two_backoff_retries(self, sleep):
        backend = RetryableQuotaNullAuthBackend(fail_twice=True)
        caller = AuthorizedTerraCaller(
            self.authorization(), backend, "main-campaign", "copilot-1.0.78",
            max_campaign_aic=None,
        )
        runtime, procedure, lexicon = clean_fixture("F1", 1)
        context = ConditionAssembler().assemble_all(runtime, procedure, lexicon)["runtime"]
        from experiments.v2_3.engine import Invocation

        result = caller(Invocation(
            "generator", "F1", 1, "runtime", 1, None,
            context.full_context, context,
        ))

        self.assertEqual(len(backend.calls), 3)
        self.assertEqual(len(backend.receipts), 3)
        sleep.assert_has_calls([call(1), call(2)])
        self.assertAlmostEqual(result.ledger_entry.ai_credits, 0.1)

    def test_second_zero_usage_auth_failure_aborts_without_third_call(self):
        backend = RetryableZeroUsageAuthBackend(fail_twice=True)
        caller = AuthorizedTerraCaller(
            self.authorization(), backend, "main-campaign", "copilot-1.0.78",
            max_campaign_aic=None,
        )
        runtime, procedure, lexicon = clean_fixture("F1", 1)
        context = ConditionAssembler().assemble_all(runtime, procedure, lexicon)["runtime"]
        from experiments.v2_3.engine import Invocation
        invocation = Invocation(
            "generator", "F1", 1, "runtime", 1, None,
            context.full_context, context,
        )

        with self.assertRaisesRegex(LiveCallerError, "durable charge receipt"):
            caller(invocation)

        self.assertEqual(len(backend.calls), 2)
        self.assertEqual(len(backend.receipts), 2)
        self.assertEqual(caller.cumulative_aic, 0.0)
        self.assertTrue(caller.campaign_aborted)

    def test_zero_usage_auth_flag_with_malformed_receipt_does_not_retry(self):
        backend = RetryableZeroUsageAuthBackend(malformed_receipt=True)
        caller = AuthorizedTerraCaller(
            self.authorization(), backend, "main-campaign", "copilot-1.0.78",
            max_campaign_aic=None,
        )
        runtime, procedure, lexicon = clean_fixture("F1", 1)
        context = ConditionAssembler().assemble_all(runtime, procedure, lexicon)["runtime"]
        from experiments.v2_3.engine import Invocation
        invocation = Invocation(
            "generator", "F1", 1, "runtime", 1, None,
            context.full_context, context,
        )

        with self.assertRaisesRegex(LiveCallerError, "durable charge receipt"):
            caller(invocation)

        self.assertEqual(len(backend.calls), 1)
        self.assertTrue(caller.campaign_aborted)
        self.assertEqual(caller.cumulative_aic, 0.0)
        with self.assertRaisesRegex(LiveCallerError, "campaign aborted"):
            caller(invocation)
        self.assertEqual(len(backend.receipts), 1)

    def test_retryable_flag_with_incomplete_usage_does_not_retry(self):
        backend = RetryableMetadataBackend()
        original_call = backend.call

        def incomplete_call(prompt, system_prompt, max_tokens):
            try:
                return original_call(prompt, system_prompt, max_tokens)
            except CopilotCLIError as exc:
                exc.receipt["usage_metadata_complete"] = False
                raise

        backend.call = incomplete_call
        caller = AuthorizedTerraCaller(
            self.authorization(), backend, "main-campaign", "copilot-1.0.78",
            max_campaign_aic=None,
        )
        runtime, procedure, lexicon = clean_fixture("F1", 1)
        context = ConditionAssembler().assemble_all(runtime, procedure, lexicon)["runtime"]
        from experiments.v2_3.engine import Invocation
        invocation = Invocation(
            "generator", "F1", 1, "runtime", 1, None,
            context.full_context, context,
        )

        with self.assertRaisesRegex(LiveCallerError, "durable charge receipt"):
            caller(invocation)

        self.assertEqual(len(backend.calls), 1)
        self.assertTrue(caller.campaign_aborted)

    def test_metadata_retry_reserves_session_cap_again(self):
        backend = RetryableMetadataBackend()
        caller = AuthorizedTerraCaller(
            self.authorization(), backend, "pilot-campaign", "copilot-1.0.78",
            max_campaign_aic=0.25,
        )
        runtime, procedure, lexicon = clean_fixture("F1", 1)
        context = ConditionAssembler().assemble_all(runtime, procedure, lexicon)["runtime"]
        from experiments.v2_3.engine import Invocation
        invocation = Invocation(
            "generator", "F1", 1, "runtime", 1, None,
            context.full_context, context,
        )

        with self.assertRaisesRegex(LiveCallerError, "cap reached before call"):
            caller(invocation)

        self.assertEqual(len(backend.calls), 1)
        self.assertAlmostEqual(caller.cumulative_aic, 0.2)
        self.assertTrue(caller.campaign_aborted)


if __name__ == "__main__":
    unittest.main()
