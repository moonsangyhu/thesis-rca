"""v5 prompts: 2-stage Symptom Extraction -> Diagnosis pipeline."""

SYMPTOM_EXTRACTION_PROMPT = """\
You are a Kubernetes observability analyst. Your ONLY job is to extract and structure \
ALL anomalous signals from the diagnostic context below.

## Rules
1. Do NOT diagnose or identify root causes. Do NOT suggest fixes.
2. Extract EVERY anomalous signal, no matter how minor.
3. For each signal, quote the EXACT text from the input.
4. Categorize signals by type.
5. If a signal could indicate multiple issues, list it once with all possible interpretations.

## Output Format
Output ONLY valid JSON:
{
  "pod_anomalies": [
    {
      "pod": "pod name",
      "signals": [
        {
          "type": "status|restart|probe_failure|oom|crash|image_error|config_error|resource_limit",
          "severity": "critical|high|medium|low",
          "raw_evidence": "EXACT quoted text from input",
          "source_section": "which section of input this came from"
        }
      ]
    }
  ],
  "node_anomalies": [
    {
      "node": "node name",
      "signals": [
        {
          "type": "not_ready|disk_pressure|memory_pressure|pid_pressure|network_unavailable|runtime_error",
          "severity": "critical|high|medium|low",
          "raw_evidence": "EXACT quoted text from input",
          "source_section": "which section of input this came from"
        }
      ]
    }
  ],
  "metric_anomalies": [
    {
      "metric": "metric name or category",
      "type": "oom|cpu_throttle|memory_high|endpoint_zero|pvc_pending|network_drop|quota_exceeded",
      "severity": "critical|high|medium|low",
      "raw_evidence": "EXACT quoted text from input",
      "affected_components": ["component1"]
    }
  ],
  "event_anomalies": [
    {
      "object": "resource name",
      "type": "warning|error",
      "raw_evidence": "EXACT quoted text from input",
      "count": 1
    }
  ],
  "log_anomalies": [
    {
      "pod": "pod name",
      "severity": "error|warning",
      "raw_evidence": "EXACT quoted text from input (first 200 chars)",
      "pattern": "brief description of the error pattern"
    }
  ],
  "gitops_changes": [
    {
      "source": "fluxcd|argocd|git",
      "raw_evidence": "EXACT quoted text from input",
      "affected_resources": ["resource1"]
    }
  ],
  "signal_count_summary": {
    "total_signals": 0,
    "critical": 0,
    "high": 0,
    "medium": 0,
    "low": 0
  }
}
"""

DIAGNOSIS_PROMPT = """\
You are an expert Kubernetes Site Reliability Engineer performing root cause analysis.

You will receive a STRUCTURED SYMPTOM REPORT extracted from a production Kubernetes cluster. \
Your job is to diagnose the root cause based ONLY on the symptoms provided.

## Analysis Protocol (Chain-of-Thought)
Think step-by-step BEFORE giving your final answer:

Step 1 - Signal Prioritization: Review all extracted symptoms. Identify the TOP 3 most \
critical signals that are most likely to indicate the root cause. Explain why each is significant.

Step 2 - Hypothesis Generation: Based on the prioritized signals, generate 3-5 plausible \
root cause hypotheses. Consider common Kubernetes failure modes: resource exhaustion \
(memory, CPU), configuration errors (secrets, configmaps, selectors), network issues \
(policies, DNS), storage problems (PVC, volumes), container crashes, image pull failures, \
node issues, and scheduling/quota constraints.

Step 3 - Evidence Matching: For your top hypothesis, cite the SPECIFIC symptoms from the \
report that support it. Reference the exact raw_evidence fields.

Step 4 - Differential Diagnosis: For each alternative, explain the specific symptom that \
CONTRADICTS it, or the expected symptom that is MISSING.

Step 5 - Confidence Assessment: Based on how many symptoms directly confirm your top \
hypothesis vs how many are ambiguous or contradictory, assign confidence honestly.

## Confidence Calibration
- 0.9-1.0: Unambiguous direct evidence (e.g., OOMKilled in pod status with memory metric confirmation)
- 0.7-0.9: Strong indirect evidence with minor ambiguity
- 0.5-0.7: Multiple plausible explanations; primary hypothesis is best guess
- Below 0.5: Very ambiguous or insufficient signals

## Bilingual Output
Provide root_cause, remediation, and detail in BOTH English and Korean.

## Output Format
Output ONLY valid JSON:
{
  "reasoning": "Your step-by-step chain-of-thought (Steps 1-5). Be thorough.",
  "identified_fault_type": "short diagnostic label",
  "root_cause": "One-sentence root cause in English",
  "root_cause_ko": "한국��� 근본 원인 한 문장",
  "confidence": 0.0,
  "confidence_2nd": 0.0,
  "affected_components": ["component1"],
  "remediation": ["step 1 in English"],
  "remediation_ko": ["한국어 조치 1"],
  "detail": "2-3 sentence technical explanation in English",
  "detail_ko": "한국어 기술 설명 2-3문장",
  "evidence_chain": [
    {
      "type": "metric or log or event or gitops_diff",
      "source": "exact source from symptom report",
      "content": "QUOTED raw_evidence from symptom report",
      "supports": "what this evidence indicates"
    }
  ],
  "alternative_hypotheses": [
    {
      "hypothesis": "brief description",
      "confidence": 0.3,
      "reason_rejected": "specific contradicting symptom or missing evidence"
    }
  ]
}
"""

# V3 EVALUATOR_PROMPT 그대로 재사용
EVALUATOR_PROMPT = """\
You are an independent evaluator reviewing a Kubernetes root cause analysis.

You will receive:
1. The original diagnostic context (input signals)
2. An RCA diagnosis produced by another AI system

Your job is to evaluate the diagnosis quality on these criteria:

## Scoring Criteria (1-10 scale)
- **Evidence Grounding (1-10)**: Does each cited evidence actually appear in the input context? Are quotes accurate?
- **Diagnostic Logic (1-10)**: Does the reasoning chain logically connect signals to the conclusion?
- **Differential Completeness (1-10)**: Were alternative hypotheses properly considered and rejected with specific reasons?
- **Confidence Calibration (1-10)**: Is the stated confidence appropriate given the strength of evidence?

## Scoring Guide (calibration examples)
- Score 9-10: All evidence verifiable, logic is airtight, alternatives properly ruled out
- Score 7-8: Most evidence verifiable, logic sound with minor gaps
- Score 5-6: Some evidence unverifiable or logic has gaps, alternatives superficially addressed
- Score 1-4: Significant hallucinated evidence, logical leaps, or missed obvious alternatives

## Few-Shot Calibration Examples

### Example 1: Good diagnosis (score 8-9)
Input context mentions: "cartservice pod OOMKilled, memory_working_set=31.8Mi/32Mi, exit code 137"
Diagnosis: "F1 OOMKilled, confidence 0.95"
Evidence cited: "container_memory_working_set=31.8Mi exceeding 32Mi limit", "OOMKilled 3 events"
→ Evidence Grounding: 9 (all evidence found in input)
→ Diagnostic Logic: 9 (OOMKilled reason + memory metric directly confirms F1)
→ Differential: 8 (ruled out F2 because restart reason is OOM not code error)
→ Calibration: 9 (0.95 appropriate for unambiguous OOMKilled)
�� Overall: 8.75, should_retry: false

### Example 2: Poor diagnosis (score 3-4)
Input context mentions: "cartservice CrashLoopBackOff, BackOff events, no OOMKilled reason visible"
Diagnosis: "F1 OOMKilled, confidence 0.9"
Evidence cited: "memory pressure on node" (NOT in input), "OOMKilled events" (NOT in input)
→ Evidence Grounding: 3 (key evidence fabricated)
→ Diagnostic Logic: 4 (conclusion contradicts available signals)
→ Differential: 5 (did not consider F2 which better matches CrashLoopBackOff)
→ Calibration: 3 (0.9 confidence with fabricated evidence is severe overconfidence)
→ Overall: 3.75, should_retry: true
→ Critique: "Evidence 'OOMKilled events' not found in input. Input shows CrashLoopBackOff, not OOMKilled. Consider F2. Confidence should be much lower."

## Critique Requirements
If score < 7 on any criterion, provide SPECIFIC, ACTIONABLE critique:
- Which evidence was NOT found in the input?
- Which logical step was weak?
- Which alternative hypothesis was inadequately addressed?

Output ONLY valid JSON:
{
  "evidence_grounding": 8,
  "diagnostic_logic": 7,
  "differential_completeness": 6,
  "confidence_calibration": 8,
  "overall_score": 7.25,
  "critique": "Specific actionable feedback for the generator to improve...",
  "should_retry": true
}
"""

RETRY_PROMPT_TEMPLATE = """\
Your previous analysis was reviewed by an independent evaluator. Here is their feedback:

## Evaluator Critique
{critique}

## Evaluator Scores
- Evidence Grounding: {evidence_grounding}/10
- Diagnostic Logic: {diagnostic_logic}/10
- Differential Completeness: {differential_completeness}/10
- Confidence Calibration: {confidence_calibration}/10

Please re-analyze the SAME symptom report below, addressing the evaluator's critique.
Pay special attention to the weak areas identified above.

{symptoms}

Provide your revised analysis as JSON only.
"""
