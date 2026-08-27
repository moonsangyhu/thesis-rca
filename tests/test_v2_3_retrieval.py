import unittest
from dataclasses import replace

from experiments.v2_3.conditions import ConditionAssembler
from experiments.v2_3.retrieval import (
    REDACTION_MARKER, BlindProcedureBuilder, RetrievalChunk,
)
from experiments.v2_3.scanner import ForbiddenLexicon, LeakageDetected


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.lexicon = ForbiddenLexicon(
            canonical_labels=("memory exhaustion",),
            aliases=("oomkill",),
            metadata=("runbooks/private-memory.md",),
            entities=("secret-workload",),
            commands=("kubectl patch deployment secret-workload",),
            harness_markers=("F1",),
        )

    def test_runtime_query_ground_truth_is_rejected(self):
        with self.assertRaises(LeakageDetected):
            BlindProcedureBuilder().build(
                runtime_context="Investigate F-1 memory exhaustion",
                runtime_query="Investigate F-1 memory exhaustion",
                chunks=(RetrievalChunk("doc", "generic procedure", 0.5, 0, 17),),
                corpus_version="corpus-1",
                lexicon=self.lexicon,
            )

    def test_runtime_query_injection_command_is_rejected(self):
        query = "kubectl patch deployment secret-workload"
        with self.assertRaises(LeakageDetected):
            BlindProcedureBuilder().build(
                runtime_context=query,
                runtime_query=query,
                chunks=(RetrievalChunk("doc", "generic procedure", 0.5, 0, 17),),
                corpus_version="corpus-1",
                lexicon=self.lexicon,
            )

    def test_runtime_observed_entity_is_allowed_as_query_evidence(self):
        query = "secret-workload reports elevated latency"
        result = BlindProcedureBuilder().build(
            runtime_context=query,
            runtime_query=query,
            chunks=(RetrievalChunk("doc", "generic review sequence", 0.5, 0, 23),),
            corpus_version="corpus-1",
            lexicon=self.lexicon,
        )
        self.assertEqual(result.provenance["query_origin"], "runtime_only")

    def test_sanitizer_masks_scanner_ngram_matches_from_long_forbidden_terms(self):
        from experiments.v2_3.scanner import ForbiddenLexicon, LeakageScanner

        lexicon = ForbiddenLexicon(
            canonical_labels=(
                "frontend exceeded its constrained CPU allocation",
            ),
            commands=(
                "Set frontend CPU limit to 10m under sustained load",
            ),
            aliases=("throttling",),
            field_values=("10m",),
            harness_markers=("F7",),
        )
        source = (
            "frontend reports constrained cpu allocation and cpu limit to 10m "
            "while cpu_throttling is present in F7_t1"
        )
        sanitized, removals = BlindProcedureBuilder().sanitize_runtime_query(
            source, source, lexicon
        )
        self.assertGreater(len(removals), 0)
        self.assertEqual(LeakageScanner().scan(sanitized, lexicon).match_count, 0)
        self.assertIn("frontend", sanitized)

    def test_short_field_value_redaction_marker_cannot_recreate_forbidden_prefix(self):
        """A mask placeholder must stay clean after compact scanner folding."""
        from experiments.v2_3.scanner import LeakageScanner

        lexicon = ForbiddenLexicon(field_values=("5m",))
        source = "inspect the five-minute rate window [5m] before triage"
        result = BlindProcedureBuilder().build(
            runtime_context="runtime error rate increased",
            runtime_query="runtime error rate increased",
            chunks=(RetrievalChunk("runbook", source, 0.9, 0, len(source)),),
            corpus_version="corpus-1",
            lexicon=lexicon,
        )
        self.assertIn(REDACTION_MARKER, result.text)
        self.assertEqual(LeakageScanner().scan(result.text, lexicon).match_count, 0)

    def test_sanitizer_masks_fault_id_internal_separator_variants(self):
        from experiments.v2_3.scanner import ForbiddenLexicon, LeakageScanner

        lexicon = ForbiddenLexicon(harness_markers=("F7", "F12"))
        for marker in ("F-7", "F_7", "F 7", "Ｆ－７", "F-12", "Ｆ＿１２"):
            with self.subTest(marker=marker):
                source = f"observed {marker} marker"
                sanitized, removals = BlindProcedureBuilder().sanitize_runtime_query(
                    source, source, lexicon
                )
                self.assertGreater(len(removals), 0)
                self.assertEqual(
                    LeakageScanner().scan(sanitized, lexicon).match_count, 0
                )

        source = "runtime uid 91af7e0 remains ordinary evidence"
        sanitized, removals = BlindProcedureBuilder().sanitize_runtime_query(
            source, source, lexicon
        )
        self.assertEqual(removals, [])
        self.assertIn("91af7e0", sanitized)

    def test_procedure_masks_separator_variant_of_compact_label(self):
        from experiments.v2_3.scanner import ForbiddenLexicon, LeakageScanner

        lexicon = ForbiddenLexicon(
            canonical_labels=("NodeNotReady",),
            aliases=("NodeNotReady",),
        )
        for source in (
            "Check whether the node not ready state persists.",
            "prefixNodeNotReadySuffix",
            "xnode not readyy",
        ):
            with self.subTest(source=source):
                result = BlindProcedureBuilder().build(
                    runtime_context="node heartbeat and runtime warnings",
                    runtime_query="node heartbeat and runtime warnings",
                    chunks=(RetrievalChunk("node-runbook", source, 0.9, 0, len(source)),),
                    corpus_version="corpus-1",
                    lexicon=lexicon,
                )
                self.assertIn(REDACTION_MARKER, result.text)
                self.assertEqual(
                    LeakageScanner().scan(result.text, lexicon).match_count, 0
                )
                matching = [
                    item for item in result.provenance["removed_spans"]
                    if item["term"] == "nodenotready"
                ]
                self.assertEqual(len(matching), 1)
                self.assertEqual(matching[0]["category"], "canonical_labels")

    def test_masking_records_retrieval_and_removed_span_provenance(self):
        source = "Inspect secret-workload, then kubectl patch deployment secret-workload."
        result = BlindProcedureBuilder().build(
            runtime_context="elevated latency and repeating warnings",
            runtime_query="elevated latency and repeating warnings",
            chunks=(RetrievalChunk("source-private-7", source, 0.81, 10, 80),),
            corpus_version="corpus-20260809",
            lexicon=self.lexicon,
        )
        self.assertNotIn("secret-workload", result.text)
        self.assertEqual(result.provenance["query_origin"], "runtime_only")
        self.assertEqual(result.provenance["corpus_version"], "corpus-20260809")
        self.assertEqual(result.provenance["candidates"][0]["source_id"], "source-private-7")
        self.assertGreater(len(result.provenance["removed_spans"]), 0)

    def test_assembler_rejects_unprovenanced_string(self):
        with self.assertRaises(TypeError):
            ConditionAssembler().assemble_all("runtime", "plain string", self.lexicon)

    def test_assembler_rejects_forged_procedure_hash(self):
        result = BlindProcedureBuilder().build(
            runtime_context="elevated latency",
            runtime_query="elevated latency",
            chunks=(RetrievalChunk("doc", "generic review sequence", 0.5, 0, 23),),
            corpus_version="corpus-1",
            lexicon=self.lexicon,
        )
        with self.assertRaisesRegex(ValueError, "hash"):
            ConditionAssembler().assemble_all(
                "runtime", replace(result, text=result.text + " tampered"), self.lexicon
            )

    def test_removed_spans_use_original_chunk_coordinates(self):
        lexicon = ForbiddenLexicon(entities=("verylongsecret", "x"))
        source = "verylongsecret abc x"
        result = BlindProcedureBuilder().build(
            runtime_context="generic warning",
            runtime_query="generic warning",
            chunks=(RetrievalChunk("doc", source, 0.5, 0, len(source)),),
            corpus_version="corpus-1",
            lexicon=lexicon,
        )
        spans = {(item["term"], item["start"], item["end"])
                 for item in result.provenance["removed_spans"]}
        self.assertIn(("verylongsecret", 0, 14), spans)
        self.assertIn(("x", 19, 20), spans)
        self.assertEqual(
            result.provenance["candidates"][0]["snapshot_locator"],
            f"corpus-1:doc:0:{len(source)}",
        )


if __name__ == "__main__":
    unittest.main()
