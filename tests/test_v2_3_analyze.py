import unittest

from experiments.v2_3.analyze import AnalysisError, analyze_rows
from experiments.v2_3.config import CONDITIONS, FAULTS, TRIALS


def complete_rows():
    rows = []
    for fault in FAULTS:
        for trial in TRIALS:
            for condition in CONDITIONS:
                correct = int(condition == "blind_procedural_rag")
                rows.append({
                    "campaign_id": "campaign-v2-3",
                    "fault_id": fault,
                    "trial": trial,
                    "context_condition": condition,
                    "correct_at_0.5": correct,
                    "correct_at_0.6": correct,
                    "correct_at_0.7": correct,
                })
    return rows


class AnalyzeTests(unittest.TestCase):
    def test_complete_paired_effect_uses_fault_clusters(self):
        result = analyze_rows(complete_rows())
        self.assertEqual(result["rows"], 180)
        self.assertEqual(result["primary_delta"], 1.0)
        self.assertEqual(result["fault_cluster_bootstrap_ci_95"], [1.0, 1.0])
        self.assertAlmostEqual(result["exact_fault_cluster_sign_flip_p"], 2 / 4096)
        self.assertTrue(result["automated_strong_support_prerequisites"])
        self.assertEqual(result["final_hypothesis_status"], "pending_human_review")

    def test_duplicate_missing_and_campaign_mixing_fail_closed(self):
        rows = complete_rows()
        with self.assertRaises(AnalysisError):
            analyze_rows(rows[:-1])
        duplicate = complete_rows()
        duplicate[-1] = dict(duplicate[0])
        with self.assertRaises(AnalysisError):
            analyze_rows(duplicate)
        mixed = complete_rows()
        mixed[-1]["campaign_id"] = "other"
        with self.assertRaises(AnalysisError):
            analyze_rows(mixed)


if __name__ == "__main__":
    unittest.main()
