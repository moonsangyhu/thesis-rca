# K8s RCA 석사 논문 실험 플랫폼

GitOps 컨텍스트(FluxCD/ArgoCD) 추가 시 LLM 기반 장애 원인 분석 정확도 향상을 검증한다.

- **System A**: Prometheus + Loki + kubectl → LLM
- **System B**: System A + GitOps + RAG → LLM
- 10 fault types (F1–F10) × 5 trials = 50 cases
- **모델 고정**: gpt-4o-mini 고정. 개선은 프레임워크 레벨에서만

문서·프롬프트는 한국어, 코드·변수명은 영어.

## Commands

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m src.rag.ingest --reset                          # RAG KB 빌드
python -m experiments.v{N}.run                             # 버전별 실험 실행
python -m experiments.v{N}.run --fault F1 --trial 3        # 단일 실험
python -m experiments.v{N}.run --dry-run                   # 테스트
python -m scripts.evaluate.analyze                         # 통계 분석
```

## Experiment Versions

- **v1**: 장애 힌트 제공 + 단순 프롬프트 (`experiments/v1/`)
- **v2**: 힌트 제거 + Chain-of-Thought (`experiments/v2/`)
- **v3**: v2 + Harness (Evaluator + Retry + Evidence Verification) (`experiments/v3/`)

각 버전은 독립 모듈. 공유 인프라는 `experiments/shared/`.

## Key Config

- `KUBECONFIG` env var (default: `~/.kube/config-k8s-lab`), namespace: `boutique`
- `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` via `.env`
- Collector endpoints: `src/collector/config.py`
- RAG settings: `src/rag/config.py`

## Rules

상세 규칙은 `rules/` 디렉토리에서 관리:

- **agents.md** — 에이전트 목록, 오케스트레이션 규칙, 토론 프로토콜
- **experiment-pipeline.md** — 1가설 순차 실행 파이프라인 (Step 0.5–5)
- **data-safety.md** — 모델 고정, 데이터 불변, 실험 격리 규칙
- **lab-workflow.md** — 스킬 카탈로그, 실험 워크플로우, Lab 환경
