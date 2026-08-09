import unittest

from experiments.v2_3.conditions import (
    ConditionAssembler, latin_square_schedule, make_length_placebo,
    require_treatment_integrity, text_metrics,
)
from experiments.v2_3.config import CONDITIONS
from experiments.v2_3.mock import clean_fixture


class ConditionTests(unittest.TestCase):
    def test_three_conditions_share_runtime_and_insertion(self):
        runtime, procedure, lexicon = clean_fixture("F1", 1)
        assembled = ConditionAssembler().assemble_all(runtime, procedure, lexicon)
        self.assertEqual(set(assembled), set(CONDITIONS))
        self.assertEqual(len({x.runtime_context_hash for x in assembled.values()}), 1)
        self.assertEqual(len({x.insertion_index for x in assembled.values()}), 1)
        self.assertEqual(len({x.common_prompt_hash for x in assembled.values()}), 1)
        require_treatment_integrity(assembled)

    def test_placebo_exactly_matches_unicode_metrics_and_is_deterministic(self):
        target = "abc 중립 절차 □"
        metrics = text_metrics(target)
        first = make_length_placebo(metrics["chars"], metrics["bytes"])
        second = make_length_placebo(metrics["chars"], metrics["bytes"])
        self.assertEqual(first, second)
        self.assertEqual(text_metrics(first), metrics)
        self.assertNotEqual(first, target)

    def test_placebo_depends_only_on_target_metrics(self):
        a = make_length_placebo(40, 40)
        b = make_length_placebo(40, 40)
        self.assertEqual(a, b)

    def test_latin_square_balances_every_position(self):
        schedule = latin_square_schedule()
        self.assertEqual(len(schedule), 60)
        for position in range(3):
            counts = {condition: 0 for condition in CONDITIONS}
            for order in schedule.values():
                counts[order[position]] += 1
            self.assertEqual(set(counts.values()), {20})

    def test_runtime_json_braces_are_preserved_literally(self):
        runtime, _, lexicon = clean_fixture("F1", 1)
        runtime = runtime + ' {"pod":"frontend"}'
        from experiments.v2_3.retrieval import BlindProcedureBuilder, RetrievalChunk
        text = "Generic reversible diagnostic procedure."
        procedure = BlindProcedureBuilder().build(
            runtime_context=runtime,
            runtime_query=runtime,
            chunks=(RetrievalChunk("generic", text, 0.5, 0, len(text)),),
            corpus_version="unit-corpus",
            lexicon=lexicon,
        )
        assembled = ConditionAssembler().assemble_all(runtime, procedure, lexicon)
        for context in assembled.values():
            self.assertIn('{"pod":"frontend"}', context.full_context)


if __name__ == "__main__":
    unittest.main()
