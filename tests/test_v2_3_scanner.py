import unittest

from experiments.v2_3.mock import clean_fixture, positive_fixture
from experiments.v2_3.scanner import (
    MAX_FORBIDDEN_TERM_TOKENS,
    ForbiddenLexicon,
    LeakageDetected,
    LeakageScanner,
    minimum_token_ngrams,
)


class ScannerTests(unittest.TestCase):
    def test_clean_fixture_has_no_matches(self):
        runtime, procedure, lexicon = clean_fixture("F1", 1)
        scanner = LeakageScanner()
        self.assertEqual(scanner.scan(runtime, lexicon, runtime_scope=True).match_count, 0)
        self.assertEqual(scanner.scan(procedure.text, lexicon).match_count, 0)

    def test_nfkc_alias_and_ngram_positive_fixture_fails_closed(self):
        text, lexicon = positive_fixture()
        report = LeakageScanner().scan(text, lexicon)
        self.assertGreaterEqual(report.match_count, 3)
        self.assertIn("aliases", report.category_counts)
        self.assertIn("commands", report.category_counts)
        with self.assertRaises(LeakageDetected):
            LeakageScanner().require_clean(text, lexicon)

    def test_legitimate_runtime_entity_is_not_scanned_but_harness_marker_is(self):
        _, _, lexicon = clean_fixture("F9", 2)
        scanner = LeakageScanner()
        self.assertEqual(scanner.scan("secret-workload observed", lexicon, runtime_scope=True).match_count, 0)
        with self.assertRaises(LeakageDetected):
            scanner.require_clean("experiment marker present", lexicon, runtime_scope=True)

    def test_runtime_oomkilled_is_preserved_but_rag_provenance_is_blocked(self):
        _, _, lexicon = clean_fixture("F1", 1)
        scanner = LeakageScanner()
        self.assertEqual(
            scanner.scan("Pod status reports OOMKilled", lexicon, runtime_scope=True).match_count,
            0,
        )
        with self.assertRaises(LeakageDetected):
            scanner.require_clean("Source: runbooks/private-memory.md", lexicon)

    def test_compact_substring_command_ngram_and_regex_alias_are_blocked(self):
        from experiments.v2_3.scanner import ForbiddenLexicon
        lexicon = ForbiddenLexicon(
            canonical_labels=("network delay",),
            commands=("kubectl patch deployment secret-workload",),
            aliases=(r"re:packet\s+loss",),
        )
        scanner = LeakageScanner()
        self.assertGreater(scanner.scan("prefixnetworkdelaypostfix", lexicon).match_count, 0)
        self.assertGreater(
            scanner.scan("kubectl patch deployment changed-target", lexicon).match_count, 0
        )
        self.assertGreater(scanner.scan("packet loss observed", lexicon).match_count, 0)

    def test_fault_id_spacing_punctuation_and_nfkc_variants_are_blocked(self):
        _, _, lexicon = clean_fixture("F12", 1)
        scanner = LeakageScanner()
        for variant in ("F-12", "F 12", "Ｆ－１２", "F_12", "Ｆ＿１２"):
            self.assertGreater(
                scanner.scan(variant, lexicon, runtime_scope=True).match_count,
                0,
                variant,
            )
        self.assertEqual(
            scanner.scan(
                "sha256=91af12e0b7c3 and uid=abcdf12ef09",
                lexicon,
                runtime_scope=True,
            ).match_count,
            0,
        )

    def test_long_terms_have_linear_minimum_ngram_count(self):
        tokens = [f"token{index}" for index in range(MAX_FORBIDDEN_TERM_TOKENS)]
        grams = minimum_token_ngrams(tokens, 3)
        self.assertEqual(len(grams), MAX_FORBIDDEN_TERM_TOKENS - 2)
        self.assertEqual(grams[0], "token0 token1 token2")
        self.assertEqual(
            grams[-1],
            f"token{MAX_FORBIDDEN_TERM_TOKENS - 3} "
            f"token{MAX_FORBIDDEN_TERM_TOKENS - 2} "
            f"token{MAX_FORBIDDEN_TERM_TOKENS - 1}",
        )

    def test_oversized_forbidden_term_fails_closed(self):
        oversized = " ".join(
            f"token{index}" for index in range(MAX_FORBIDDEN_TERM_TOKENS + 1)
        )
        with self.assertRaisesRegex(ValueError, "token limit"):
            LeakageScanner().scan(
                "ordinary runtime evidence",
                ForbiddenLexicon(commands=(oversized,)),
            )


if __name__ == "__main__":
    unittest.main()
