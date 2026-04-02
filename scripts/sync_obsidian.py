#!/usr/bin/env python3
"""Watch experiment_results CSV and sync to Obsidian note."""
import csv
import json
import time
from pathlib import Path
from datetime import datetime

RESULTS_DIR = Path(__file__).parent.parent / "results"
RESULTS_CSV_V1 = RESULTS_DIR / "experiment_results.csv"
RESULTS_CSV_V2 = RESULTS_DIR / "experiment_results_v2.csv"
GROUND_TRUTH = RESULTS_DIR / "ground_truth.csv"
RAW_DIR = RESULTS_DIR / "raw"
OBSIDIAN_DIR = Path.home() / "Documents/ms/jumpup/대학원"
POLL_INTERVAL = 30


def read_csv(path):
    rows = []
    if path.exists():
        with open(path) as f:
            for r in csv.DictReader(f):
                rows.append(r)
    return rows


def load_ground_truth():
    gt = {}
    for r in read_csv(GROUND_TRUTH):
        key = (r["fault_id"], r.get("trial", "1"))
        gt[key] = r
    return gt


def find_raw_context(fault_id, trial, system):
    pattern = f"{fault_id}_t{trial}_{system}_*.json"
    matches = sorted(RAW_DIR.glob(pattern))
    if not matches:
        return None
    try:
        with open(matches[-1]) as f:
            data = json.load(f)
        return data.get("context", "")
    except Exception:
        return None


def _parse_json_field(val):
    """Parse a JSON string field from CSV, return list/dict or empty list."""
    if not val or val in ("", "[]", "{}"):
        return []
    try:
        return json.loads(val) if isinstance(val, str) else val
    except Exception:
        return []


def _correct_label(val):
    """Return O/X/ABSTAIN for correct field."""
    if val == "1":
        return "O"
    elif val == "-1":
        return "ABSTAIN"
    return "X"


def build_note_v1(rows, gt):
    """Build Obsidian note for v1 experiment."""
    trials = {}
    for r in rows:
        key = (r["fault_id"], r["trial"])
        if key not in trials:
            trials[key] = {"rows": {}}
        trials[key]["rows"][r["system"]] = r

    total_trials = len(trials)
    a_correct = sum(1 for t in trials.values()
                    if t["rows"].get("A", {}).get("correct") == "1")
    b_correct = sum(1 for t in trials.values()
                    if t["rows"].get("B", {}).get("correct") == "1")
    a_pct = f"{a_correct}/{total_trials} ({100*a_correct/total_trials:.0f}%)" if total_trials else "-"
    b_pct = f"{b_correct}/{total_trials} ({100*b_correct/total_trials:.0f}%)" if total_trials else "-"

    total_prompt = sum(int(r.get("prompt_tokens", 0) or 0) for r in rows)
    total_completion = sum(int(r.get("completion_tokens", 0) or 0) for r in rows)
    cost = (total_prompt * 0.15 + total_completion * 0.6) / 1_000_000

    detail_sections = []
    for (fid, trial), data in sorted(trials.items()):
        ra = data["rows"].get("A", {})
        rb = data["rows"].get("B", {})
        ts = (ra or rb).get("timestamp", "")[:16]
        gt_row = gt.get((fid, trial), {})
        fault_name = gt_row.get("fault_name", fid)
        target = gt_row.get("target_service", "?")
        injection = gt_row.get("injection_method", "")
        expected_cause = gt_row.get("expected_root_cause", "")
        a_mark = _correct_label(ra.get("correct", "0"))
        b_mark = _correct_label(rb.get("correct", "0"))
        a_pred = ra.get("identified_fault_type", "-")
        b_pred = rb.get("identified_fault_type", "-")
        a_conf = ra.get("confidence", "-")
        b_conf = rb.get("confidence", "-")
        a_cause = ra.get("root_cause", "-")
        b_cause = rb.get("root_cause", "-")
        a_remed = (ra.get("remediation", "-") or "-").replace("|", " / ")
        b_remed = (rb.get("remediation", "-") or "-").replace("|", " / ")

        ctx_a = find_raw_context(fid, trial, "A")
        ctx_b = find_raw_context(fid, trial, "B")
        ctx_a_block = f"\n<details><summary>System A LLM 입력 ({len(ctx_a):,} chars)</summary>\n\n```\n{ctx_a}\n```\n\n</details>\n" if ctx_a else ""
        ctx_b_block = f"\n<details><summary>System B LLM 입력 ({len(ctx_b):,} chars)</summary>\n\n```\n{ctx_b}\n```\n\n</details>\n" if ctx_b else ""

        section = f"""### {fid} Trial {trial} — {fault_name} ({target}) {a_mark}/{b_mark}
> **시간**: {ts}
> **주입**: {injection}
> **정답**: {expected_cause}

| | System A (Obs Only) | System B (+ GitOps + RAG) |
|---|---|---|
| **예측** | {a_pred} ({a_conf}) {a_mark} | {b_pred} ({b_conf}) {b_mark} |
| **근본 원인** | {a_cause} | {b_cause} |
| **조치 방안** | {a_remed} | {b_remed} |
{ctx_a_block}{ctx_b_block}---
"""
        detail_sections.append(section)

    details = "\n".join(detail_sections) if detail_sections else "(아직 결과 없음)"
    errors = [r for r in rows if r.get("error")]
    error_section = ""
    if errors:
        error_section = "\n## 오류 발생\n\n"
        for e in errors:
            error_section += f"- {e['fault_id']} t{e['trial']} {e['system']}: {e['error']}\n"

    return f"""# RCA 실험 실시간 로그 (v1)

> 실험 시작: 2026-04-02 18:15
> 모델: gpt-4o-mini (openai)
> 범위: F1~F10 x 5 trials = 50건 (System A/B)
> 마지막 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M')}

## 요약 통계

| 항목 | 값 |
|------|-----|
| 완료 | {total_trials} / 50 |
| System A 정확도 | {a_pct} |
| System B 정확도 | {b_pct} |
| 총 토큰 | {total_prompt + total_completion:,} (prompt: {total_prompt:,}, comp: {total_completion:,}) |
| 추정 비용 | ${cost:.4f} |
{error_section}
## 실험 상세 결과

{details}"""


def build_note_v2(rows, gt):
    """Build Obsidian note for v2 experiment (harness + CoT + bilingual)."""
    trials = {}
    for r in rows:
        key = (r["fault_id"], r["trial"])
        if key not in trials:
            trials[key] = {"rows": {}}
        trials[key]["rows"][r["system"]] = r

    total_trials = len(trials)
    a_correct = sum(1 for t in trials.values()
                    if t["rows"].get("A", {}).get("correct") == "1")
    b_correct = sum(1 for t in trials.values()
                    if t["rows"].get("B", {}).get("correct") == "1")
    a_abstained = sum(1 for t in trials.values()
                      if t["rows"].get("A", {}).get("correct") == "-1")
    b_abstained = sum(1 for t in trials.values()
                      if t["rows"].get("B", {}).get("correct") == "-1")
    a_pct = f"{a_correct}/{total_trials} ({100*a_correct/total_trials:.0f}%)" if total_trials else "-"
    b_pct = f"{b_correct}/{total_trials} ({100*b_correct/total_trials:.0f}%)" if total_trials else "-"

    # Faithfulness averages
    a_faith_vals = [float(t["rows"]["A"].get("faithfulness_score", 0) or 0)
                    for t in trials.values() if "A" in t["rows"]]
    b_faith_vals = [float(t["rows"]["B"].get("faithfulness_score", 0) or 0)
                    for t in trials.values() if "B" in t["rows"]]
    a_faith_avg = f"{sum(a_faith_vals)/len(a_faith_vals):.2f}" if a_faith_vals else "-"
    b_faith_avg = f"{sum(b_faith_vals)/len(b_faith_vals):.2f}" if b_faith_vals else "-"

    # Evaluator averages
    a_eval_vals = [float(t["rows"]["A"].get("eval_overall_score", 0) or 0)
                   for t in trials.values() if "A" in t["rows"]]
    b_eval_vals = [float(t["rows"]["B"].get("eval_overall_score", 0) or 0)
                   for t in trials.values() if "B" in t["rows"]]
    a_eval_avg = f"{sum(a_eval_vals)/len(a_eval_vals):.1f}" if a_eval_vals else "-"
    b_eval_avg = f"{sum(b_eval_vals)/len(b_eval_vals):.1f}" if b_eval_vals else "-"

    # Retry counts
    a_retried = sum(1 for t in trials.values()
                    if int(t["rows"].get("A", {}).get("retry_count", 0) or 0) > 0)
    b_retried = sum(1 for t in trials.values()
                    if int(t["rows"].get("B", {}).get("retry_count", 0) or 0) > 0)

    total_prompt = sum(int(r.get("prompt_tokens", 0) or 0) for r in rows)
    total_completion = sum(int(r.get("completion_tokens", 0) or 0) for r in rows)
    cost = (total_prompt * 0.15 + total_completion * 0.6) / 1_000_000

    # Build detail sections
    detail_sections = []
    for (fid, trial), data in sorted(trials.items()):
        ra = data["rows"].get("A", {})
        rb = data["rows"].get("B", {})
        ts = (ra or rb).get("timestamp", "")[:16]
        gt_row = gt.get((fid, trial), {})
        fault_name = gt_row.get("fault_name", fid)
        target = gt_row.get("target_service", "?")
        injection = gt_row.get("injection_method", "")
        expected_cause = gt_row.get("expected_root_cause", "")

        a_mark = _correct_label(ra.get("correct", "0"))
        b_mark = _correct_label(rb.get("correct", "0"))
        a_pred = ra.get("identified_fault_type", "-")
        b_pred = rb.get("identified_fault_type", "-")
        a_conf = ra.get("confidence", "-")
        b_conf = rb.get("confidence", "-")
        a_cause = ra.get("root_cause", "-")
        b_cause = rb.get("root_cause", "-")
        a_cause_ko = ra.get("root_cause_ko", "-") or "-"
        b_cause_ko = rb.get("root_cause_ko", "-") or "-"
        a_remed = (ra.get("remediation", "-") or "-").replace("|", " / ")
        b_remed = (rb.get("remediation", "-") or "-").replace("|", " / ")
        a_remed_ko = (ra.get("remediation_ko", "-") or "-").replace("|", " / ")
        b_remed_ko = (rb.get("remediation_ko", "-") or "-").replace("|", " / ")
        a_faith = ra.get("faithfulness_score", "-")
        b_faith = rb.get("faithfulness_score", "-")
        a_abstain = ra.get("abstention_reason", "") or "-"
        b_abstain = rb.get("abstention_reason", "") or "-"

        # Evidence chain (System B primarily)
        def _format_evidence(row_data):
            ev_list = _parse_json_field(row_data.get("evidence_chain", ""))
            if not ev_list:
                return "(없음)"
            lines = []
            for ev in ev_list:
                verified = "V" if ev.get("verified", False) else "X"
                mr = ev.get("match_ratio", "?")
                lines.append(
                    f"- [{ev.get('type', '?')}] {verified} ({mr}) "
                    f"{ev.get('source', '')}: {ev.get('supports', '')}"
                )
            return "\n".join(lines)

        def _format_alternatives(row_data):
            alt_list = _parse_json_field(row_data.get("alternative_hypotheses", ""))
            if not alt_list:
                return "(없음)"
            lines = []
            for a in alt_list:
                c = a.get("confidence", "?")
                lines.append(f"- {a.get('fault_type', '?')} ({c}): {a.get('reason_rejected', '')}")
            return "\n".join(lines)

        ev_a = _format_evidence(ra)
        ev_b = _format_evidence(rb)
        alt_a = _format_alternatives(ra)
        alt_b = _format_alternatives(rb)

        # CoT reasoning (collapsible)
        reasoning_b = rb.get("reasoning", "") or ""
        reasoning_a = ra.get("reasoning", "") or ""
        cot_block = ""
        if reasoning_b:
            cot_block += f"\n<details><summary>CoT 추론 — System B</summary>\n\n{reasoning_b}\n\n</details>\n"
        if reasoning_a:
            cot_block += f"\n<details><summary>CoT 추론 — System A</summary>\n\n{reasoning_a}\n\n</details>\n"

        # LLM input context (collapsible)
        ctx_a = find_raw_context(fid, trial, "A")
        ctx_b = find_raw_context(fid, trial, "B")
        ctx_block = ""
        if ctx_a:
            ctx_block += f"\n<details><summary>System A LLM 입력 ({len(ctx_a):,} chars)</summary>\n\n```\n{ctx_a}\n```\n\n</details>\n"
        if ctx_b:
            ctx_block += f"\n<details><summary>System B LLM 입력 ({len(ctx_b):,} chars)</summary>\n\n```\n{ctx_b}\n```\n\n</details>\n"

        # Evaluator scores
        def _eval_block(row_data):
            es = row_data.get("eval_overall_score", "")
            if not es or es == "0" or es == "0.0":
                return ""
            eg = row_data.get("eval_evidence_grounding", "-")
            dl = row_data.get("eval_diagnostic_logic", "-")
            dc = row_data.get("eval_differential_completeness", "-")
            cc = row_data.get("eval_confidence_calibration", "-")
            rc = row_data.get("retry_count", "0")
            crit = row_data.get("eval_critique", "-") or "-"
            return (
                f"| Evidence Grounding | {eg}/10 |\n"
                f"| Diagnostic Logic | {dl}/10 |\n"
                f"| Differential Completeness | {dc}/10 |\n"
                f"| Confidence Calibration | {cc}/10 |\n"
                f"| **Overall** | **{es}/10** |\n"
                f"| Retry 횟수 | {rc} |\n"
                f"| Critique | {crit[:150]} |"
            )

        eval_a = _eval_block(ra)
        eval_b = _eval_block(rb)
        eval_section = ""
        if eval_a or eval_b:
            eval_section = "\n**Evaluator 평가:**\n"
            if eval_a:
                eval_section += f"\nSystem A:\n| 항목 | 점수 |\n|------|------|\n{eval_a}\n"
            if eval_b:
                eval_section += f"\nSystem B:\n| 항목 | 점수 |\n|------|------|\n{eval_b}\n"

        section = f"""### {fid} Trial {trial} — {fault_name} ({target}) {a_mark}/{b_mark}
> **시간**: {ts}
> **주입**: {injection}
> **정답**: {expected_cause}

| | System A (Obs Only) | System B (+ GitOps + RAG) |
|---|---|---|
| **예측** | {a_pred} ({a_conf}) {a_mark} | {b_pred} ({b_conf}) {b_mark} |
| **근본 원인** | {a_cause} | {b_cause} |
| **근본 원인 (KO)** | {a_cause_ko} | {b_cause_ko} |
| **조치 방안** | {a_remed} | {b_remed} |
| **조치 방안 (KO)** | {a_remed_ko} | {b_remed_ko} |
| **근거 충실도** | {a_faith} | {b_faith} |
| **기권 사유** | {a_abstain} | {b_abstain} |
{eval_section}
**Evidence Chain (System A):**
{ev_a}

**Evidence Chain (System B):**
{ev_b}

**기각된 대안 (System A):**
{alt_a}

**기각된 대안 (System B):**
{alt_b}
{cot_block}{ctx_block}---
"""
        detail_sections.append(section)

    details = "\n".join(detail_sections) if detail_sections else "(아직 결과 없음)"
    errors = [r for r in rows if r.get("error")]
    error_section = ""
    if errors:
        error_section = "\n## 오류 발생\n\n"
        for e in errors:
            error_section += f"- {e['fault_id']} t{e['trial']} {e['system']}: {e['error']}\n"

    return f"""# RCA 실험 실시간 로그 (v2 — Harness + CoT)

> 모델: gpt-4o-mini (openai)
> 범위: F1~F10 x 5 trials = 50건 (System A/B)
> Harness: Evidence 교차검증 + 다층 기권 판단
> 마지막 업데이트: {datetime.now().strftime('%Y-%m-%d %H:%M')}

## 요약 통계

| 항목 | System A | System B |
|------|----------|----------|
| 정확도 | {a_pct} | {b_pct} |
| 기권 | {a_abstained}/{total_trials} | {b_abstained}/{total_trials} |
| 근거 충실도 (avg) | {a_faith_avg} | {b_faith_avg} |
| Evaluator 점수 (avg) | {a_eval_avg} | {b_eval_avg} |
| Retry 발생 | {a_retried}/{total_trials} | {b_retried}/{total_trials} |

| 항목 | 값 |
|------|-----|
| 완료 | {total_trials} / 50 |
| 총 토큰 | {total_prompt + total_completion:,} (prompt: {total_prompt:,}, comp: {total_completion:,}) |
| 추정 비용 | ${cost:.4f} |
{error_section}
## 실험 상세 결과

{details}"""


def main():
    last_count_v1 = 0
    last_count_v2 = 0
    gt = load_ground_truth()
    print(f"Ground truth: {len(gt)} entries loaded")
    print(f"Watching v1: {RESULTS_CSV_V1}")
    print(f"Watching v2: {RESULTS_CSV_V2}")
    print(f"Poll interval: {POLL_INTERVAL}s")

    while True:
        # v1
        rows_v1 = read_csv(RESULTS_CSV_V1)
        if len(rows_v1) != last_count_v1:
            note = build_note_v1(rows_v1, gt)
            (OBSIDIAN_DIR / "thesis-experiment-log.md").write_text(note)
            print(f"[{datetime.now():%H:%M:%S}] v1 updated: {len(rows_v1)} rows")
            last_count_v1 = len(rows_v1)

        # v2
        rows_v2 = read_csv(RESULTS_CSV_V2)
        if len(rows_v2) != last_count_v2:
            note = build_note_v2(rows_v2, gt)
            (OBSIDIAN_DIR / "thesis-experiment-log-v2.md").write_text(note)
            print(f"[{datetime.now():%H:%M:%S}] v2 updated: {len(rows_v2)} rows")
            last_count_v2 = len(rows_v2)

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
