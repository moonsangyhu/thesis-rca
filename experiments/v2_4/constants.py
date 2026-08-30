"""Preregistered constants and schemas for V2.4."""

from __future__ import annotations

AUDIT_SCHEMA_VERSION = "v2.4-measurement-audit-1"
IDENTITY_SCHEMA_VERSION = "v2.4-identity-json-1"
EXPECTED_CAMPAIGN_ID = "v2-3-codex-20260830-primary03"
EXPECTED_SEED_HASH = "b6d27015ce04ec86b7296e3762b2a38eb98ba5b5e602ca6c357d7533f62fbbe8"
COLLECTION_NAME = "k8s-rca-knowledge"
CONDITIONS = ("runtime", "length_placebo", "blind_procedural_rag")
SELECTED_INCIDENTS = (
    ("F1", 2), ("F1", 3), ("F2", 1), ("F3", 3),
    ("F3", 4), ("F4", 1), ("F5", 2), ("F5", 3),
    ("F6", 5), ("F7", 1), ("F7", 3), ("F8", 3),
)

CORRECTNESS_FIELDS = (
    "case_id", "expected_target_service", "expected_root_cause",
    "expected_primary_symptoms", "expected_metrics", "expected_log_patterns",
    "expected_recovery_action", "candidate_identified_fault_type",
    "candidate_root_cause", "candidate_remediation", "correctness_0_1_2_A",
    "reason_codes", "rationale",
)
SEMANTIC_FIELDS = (
    "context_id", "audit_reference_label_aliases", "audit_reference_entities",
    "audit_reference_mechanism", "audit_reference_injection_signature",
    "procedure_text", "severity_L0_L1_L2_L3", "label_exposed",
    "entity_exposed", "injection_specific", "generic_procedure", "rationale",
)
REASON_CODES = frozenset({
    "WRONG_FAMILY", "WRONG_TARGET", "MECHANISM_MISSING", "CAUSAL_CHAIN_WEAK",
    "EVIDENCE_CONTRADICTION", "REMEDIATION_INADEQUATE", "REFERENCE_AMBIGUOUS",
    "OUTPUT_UNPARSABLE",
})
