import unittest
from dataclasses import replace

from experiments.v2_3.conditions import ConditionAssembler
from experiments.v2_3.engine import RCAEngineV2_3, majority
from experiments.v2_3.ledger import CallLedger, ProvenanceError
from experiments.v2_3.mock import DeterministicMockCaller, clean_fixture
from experiments.v2_3.scanner import sha256_text


class EngineTests(unittest.TestCase):
    def test_k3_m3_aggregation_creates_twelve_calls(self):
        runtime, procedure, lexicon = clean_fixture("F1", 1)
        context = ConditionAssembler().assemble_all(runtime, procedure, lexicon)["runtime"]
        engine = RCAEngineV2_3(DeterministicMockCaller("unit"))
        row = engine.analyze_condition(context, "F1", 1, judge_reference="sealed answer")
        self.assertEqual(len(engine.ledger.entries), 12)
        self.assertEqual(row["generation_agreement"], 2 / 3)
        self.assertEqual(row["representative_score"], 0.75)
        self.assertEqual(row["correct_at_0.5"], 1)

    def test_three_way_tie_uses_first_call_order_and_marks_split(self):
        self.assertEqual(majority(["a", "b", "c"]), ("a", 1 / 3, True))

    def test_mock_sessions_are_unique_and_provenance_complete(self):
        runtime, procedure, lexicon = clean_fixture("F2", 2)
        context = ConditionAssembler().assemble_all(runtime, procedure, lexicon)["length_placebo"]
        engine = RCAEngineV2_3(DeterministicMockCaller("unit"))
        engine.analyze_condition(context, "F2", 2, judge_reference="sealed answer")
        sessions = [entry.session_id for entry in engine.ledger.entries]
        self.assertEqual(len(sessions), len(set(sessions)))
        for entry in engine.ledger.entries:
            entry.validate()
            self.assertEqual(entry.input_tokens, "unsupported/not_reported")

    def test_duplicate_session_fails_closed(self):
        runtime, procedure, lexicon = clean_fixture("F2", 2)
        context = ConditionAssembler().assemble_all(runtime, procedure, lexicon)["runtime"]
        caller = DeterministicMockCaller("unit")
        first = caller(type("I", (), {
            "role": "generator", "fault_id": "F2", "trial": 2,
            "condition": "runtime", "generation_repeat": 1,
            "judge_repeat": None, "prompt": context.full_context, "context": context,
        })())
        ledger = CallLedger()
        ledger.append(first.ledger_entry)
        with self.assertRaises(ProvenanceError):
            ledger.append(first.ledger_entry)

    def test_missing_aic_fails_closed(self):
        runtime, procedure, lexicon = clean_fixture("F3", 1)
        context = ConditionAssembler().assemble_all(runtime, procedure, lexicon)["runtime"]
        caller = DeterministicMockCaller("unit")
        invocation = type("I", (), {
            "role": "generator", "fault_id": "F3", "trial": 1,
            "condition": "runtime", "generation_repeat": 1,
            "judge_repeat": None, "prompt": context.full_context, "context": context,
        })()
        entry = replace(caller(invocation).ledger_entry, ai_credits=None)
        with self.assertRaises(ProvenanceError):
            entry.validate()

    def test_cross_field_provenance_tampering_fails_closed(self):
        runtime, procedure, lexicon = clean_fixture("F3", 1)
        context = ConditionAssembler().assemble_all(runtime, procedure, lexicon)["runtime"]
        caller = DeterministicMockCaller("unit")
        invocation = type("I", (), {
            "role": "generator", "fault_id": "F3", "trial": 1,
            "condition": "runtime", "generation_repeat": 1,
            "judge_repeat": None, "prompt": context.full_context, "context": context,
        })()
        entry = replace(caller(invocation).ledger_entry, runtime_context_hash="0" * 64)
        with self.assertRaisesRegex(ProvenanceError, "runtime_context_hash"):
            CallLedger().append(entry, invocation)

    def test_invalid_and_nan_judge_payloads_fail_closed(self):
        runtime, procedure, lexicon = clean_fixture("F4", 1)
        context = ConditionAssembler().assemble_all(runtime, procedure, lexicon)["runtime"]

        class BadJudgeCaller(DeterministicMockCaller):
            def __call__(self, invocation):
                result = super().__call__(invocation)
                if invocation.role == "judge":
                    return replace(result, payload={"correctness_score": float("nan")})
                return result

        with self.assertRaisesRegex(ValueError, "finite"):
            RCAEngineV2_3(BadJudgeCaller("unit")).analyze_condition(
                context, "F4", 1, judge_reference="sealed answer"
            )

    def test_judge_receives_redacted_context_and_blinded_prompt(self):
        runtime, procedure, lexicon = clean_fixture("F5", 1)
        context = ConditionAssembler().assemble_all(runtime, procedure, lexicon)[
            "blind_procedural_rag"
        ]
        seen = []

        class RecordingCaller(DeterministicMockCaller):
            def __call__(self, invocation):
                if invocation.role == "judge":
                    seen.append(invocation)
                return super().__call__(invocation)

        engine = RCAEngineV2_3(RecordingCaller("unit"))
        engine.analyze_condition(
            context, "F5", 1, judge_reference="sealed answer"
        )
        self.assertEqual(len(seen), 9)
        for invocation in seen:
            self.assertNotIn(procedure.text, invocation.prompt)
            self.assertEqual(invocation.fault_id, "BLINDED")
            self.assertEqual(invocation.trial, 0)
            self.assertEqual(invocation.condition, "blinded")
            self.assertEqual(invocation.context.condition, "blinded")
            self.assertNotIn("blind_procedural_rag", invocation.prompt)
            self.assertIn("sealed answer", invocation.prompt)
            self.assertEqual(invocation.context.additional_context_hash, sha256_text(""))
            self.assertEqual(invocation.context.additional_context, "")
            self.assertEqual(invocation.context.runtime_context, "")
        for entry in (item for item in engine.ledger.entries if item.role == "judge"):
            self.assertEqual(entry.runtime_context_hash, sha256_text(""))
            self.assertEqual(entry.additional_context_hash, sha256_text(""))
            self.assertEqual(entry.linked_runtime_context_hash, context.runtime_context_hash)
            self.assertEqual(
                entry.linked_additional_context_hash, context.additional_context_hash
            )

    def test_planned_majority_score_median_drives_threshold(self):
        runtime, procedure, lexicon = clean_fixture("F6", 1)
        context = ConditionAssembler().assemble_all(runtime, procedure, lexicon)["runtime"]

        class AsymmetricCaller(DeterministicMockCaller):
            def __call__(self, invocation):
                result = super().__call__(invocation)
                if invocation.role == "judge":
                    score = 0.4 if invocation.generation_repeat == 1 else 0.8
                    return replace(result, payload={"correctness_score": score})
                return result

        row = RCAEngineV2_3(AsymmetricCaller("unit")).analyze_condition(
            context, "F6", 1, judge_reference="sealed answer"
        )
        self.assertAlmostEqual(row["selected_label_aggregate_score"], 0.6)
        self.assertAlmostEqual(row["representative_score"], 0.6)
        self.assertIn(row["representative_sample_score"], (0.4, 0.8))
        self.assertEqual(row["correct_at_0.5"], 1)

    def test_nonfinite_tokens_and_inconsistent_cumulative_aic_fail_closed(self):
        runtime, procedure, lexicon = clean_fixture("F7", 1)
        context = ConditionAssembler().assemble_all(runtime, procedure, lexicon)["runtime"]
        caller = DeterministicMockCaller("unit")
        invocation = type("I", (), {
            "role": "generator", "fault_id": "F7", "trial": 1,
            "condition": "runtime", "generation_repeat": 1,
            "judge_repeat": None, "prompt": context.full_context, "context": context,
        })()
        entry = caller(invocation).ledger_entry
        with self.assertRaises(ProvenanceError):
            replace(entry, output_tokens=float("nan")).validate()
        with self.assertRaises(ProvenanceError):
            replace(entry, ai_credits=2.0, cumulative_ai_credits=0.0).validate()


if __name__ == "__main__":
    unittest.main()
