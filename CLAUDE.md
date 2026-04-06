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
python -m scripts.run_experiment                           # 전체 실험
python -m scripts.run_experiment --fault F1 --trial 3      # 단일 실험
python -m scripts.run_experiment --dry-run                 # 테스트
python -m scripts.evaluate.analyze                         # 통계 분석
```

## Sub-agents

복잡한 작업은 반드시 sub-agent를 활용하여 분업한다. `.claude/agents/` 에 정의된 에이전트:

- **`@experiment`** — 실험 운영 (fault injection, signal collection, RCA, 통계 분석). sonnet 모델 사용.
- **`@paper-writer`** — 논문 작성 (results/ 데이터 기반 학술 글쓰기). opus 모델 사용.

협업 패턴: experiment → `results/` 에 CSV/JSON 저장 → paper-writer가 읽어서 논문 반영.

## Key Config

- `KUBECONFIG` env var (default: `~/.kube/config-k8s-lab`), namespace: `boutique`
- `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` via `.env`
- Collector endpoints: `src/collector/config.py`
- RAG settings: `src/rag/config.py`

## Language

문서·프롬프트는 한국어, 코드·변수명은 영어.
