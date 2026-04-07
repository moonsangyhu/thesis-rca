# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

K8s RCA 석사 논문 실험 플랫폼. GitOps 컨텍스트(FluxCD/ArgoCD) 추가 시 LLM 기반 장애 원인 분석 정확도 향상을 검증한다.
- **System A**: Prometheus + Loki + kubectl → LLM
- **System B**: System A + GitOps + RAG → LLM
- 10 fault types (F1–F10) × 5 trials = 50 cases

## Commands

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m src.rag.ingest --reset                          # RAG KB 빌드

# 버전별 실험 실행 (experiments/ 모듈)
python -m experiments.v1.run                               # v1: 힌트+단순
python -m experiments.v2.run                               # v2: 힌트제거+CoT
python -m experiments.v3.run                               # v3: v2+Harness
python -m experiments.v2.run --fault F1 --trial 3          # 단일 실험
python -m experiments.v2.run --dry-run                     # 테스트
python -m experiments.v2.run --resume                      # 이어하기

python -m scripts.evaluate.analyze                         # 통계 분석
```

## Experiment Versions

- **v1**: F1-F10 장애 힌트 제공 + 단순 프롬프트 (`experiments/v1/`)
- **v2**: 장애 힌트 제거 + Chain-of-Thought (`experiments/v2/`)
- **v3**: v2 + Harness (Evaluator + Retry + Evidence Verification) (`experiments/v3/`)

각 버전은 독립 모듈. 공유 인프라는 `experiments/shared/`.

## Sub-agents

복잡한 작업은 반드시 sub-agent를 활용하여 분업한다. 사용자는 **오케스트레이터**로서 에이전트들을 조율한다.

### 에이전트 목록 (`.claude/agents/`)

- **`@hypothesis-reviewer`** — 가설 검토 (방법론 비평, 교란 변수 식별, 대안 가설 제안). opus.
- **`@experiment-planner`** — 실험 계획 수립 (파라미터 결정, 선행 결과 분석, 계획서 작성). opus.
- **`@experiment`** — 실험 운영 (fault injection, signal collection, RCA, 통계 분석). sonnet.
- **`@experiment-modifier`** — 실험 시나리오 수정 (결과 분석, 교훈 도출, 코드 개선, 변경 이력 기록). sonnet.
- **`@results-writer`** — 결과 분석·요약 (CSV/JSON → 분석 리포트). sonnet.
- **`@paper-writer`** — 논문 작성 (results/ 데이터 기반 학술 글쓰기). opus.

### 실험 파이프라인 (강제)

사용자가 "다음 실험 진행해", "실험 해줘" 등 실험 수행을 지시하면 **반드시 아래 4단계를 순서대로** 실행한다. 단계를 건너뛰거나 순서를 바꾸지 않는다.

```
Step 1: @experiment-planner  →  실험 계획서 작성 (docs/plans/experiment_plan_v{N}.md)
                                   이전 결과 깊이 분석 → 개선 가설 → 상세 계획서 → commit-push
                                   ⬇
Step 2: @hypothesis-reviewer  →  계획서 피드백 (docs/plans/review_v{N}.md)
                                   방법론 비평, 교란 변수, 대안 가설 → commit-push
                                   ⬇
Step 3: 피드백 반영 → @experiment 실험 수행
         - 수정 필요시: @experiment-modifier가 코드 수정 → commit-push → @experiment 실행
         - 수정 불필요시: @experiment가 바로 실행
         - 실험은 계획서(docs/plans/experiment_plan_v{N}.md) 기반으로만 수행
         - nohup으로 백그라운드 실행, /experiment-status로 모니터링
                                   ⬇
Step 4: @results-writer  →  결과 리포트 작성 (results/analysis_v{N}.md)
                              통계 요약, fault별 비교, key findings → commit-push
```

**오케스트레이터(Claude Code)의 역할:**
- 각 단계의 에이전트를 순서대로 호출
- 이전 단계의 산출물(계획서, 리뷰)을 다음 에이전트에게 전달
- Step 2 피드백 후 수정 필요 여부를 판단하여 Step 3 분기
- 각 단계 완료 시 사용자에게 요약 보고

**산출물 경로:**
- 실험 계획서: `docs/plans/experiment_plan_v{N}.md`
- 가설 리뷰: `docs/plans/review_v{N}.md`
- 실험 결과: `results/experiment_results_v{N}.csv`
- 분석 리포트: `results/analysis_v{N}.md`

### 에이전트 간 토론

에이전트 간 **토론**: 각 에이전트는 다른 에이전트의 산출물에 대해 의견을 제시하고, 이견이 있으면 근거를 들어 토론한다. 최종 결정은 오케스트레이터(사용자)가 내린다.

### 공통 규칙

- 수정 작업 후 반드시 `/changelog` 스킬로 변경 이력 기록
- 작업 완료 후 `/commit-push` 스킬로 커밋·푸시

### 불문률 (모든 에이전트 공통)

1. **실험 실행 중에는 커밋·푸시·브랜치 변경 등 실험을 중단시킬 수 있는 행위 절대 금지**
2. 실험 중 코드 수정이 필요하면: 실험 중단 → 수정 → `/changelog` → `/commit-push` → 실험 재개
3. `results/*.csv`, `results/raw/*.json` 원본 데이터 수정·삭제 절대 금지

## Skills

- **`/lab-tunnel`** — 실험 환경 터널링 + preflight check (K8s API, Prometheus, Loki)
- **`/lab-restore`** — 실험 후 환경 정상화 (fault 잔여물 제거, 디스크 정리, 모니터링 복원)
- **`/changelog`** — 변경 이력 기록. 모든 에이전트가 수정 작업 후 반드시 호출
- **`/commit-push`** — Git commit & push (실험 중이 아닐 때만)

실험 워크플로우: `/lab-tunnel` → 실험 수행 → `/lab-restore` → 다음 실험

## Lab Environment

실험 환경 상세 정보: `docs/lab-environment.md`

## Key Config

- `KUBECONFIG` env var (default: `~/.kube/config-k8s-lab`), namespace: `boutique`
- `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` via `.env`
- Collector endpoints: `src/collector/config.py`
- RAG settings: `src/rag/config.py`

## Language

문서·프롬프트는 한국어, 코드·변수명은 영어.
