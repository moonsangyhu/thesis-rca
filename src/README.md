# src/ — RCA 파이프라인 소스코드

## 목적

Kubernetes 클러스터 장애에 대한 자동화된 근본 원인 분석(RCA)을 수행하는 Python 파이프라인이다. 관측 데이터(메트릭, 로그, 이벤트)를 수집하고, 선택적으로 GitOps 컨텍스트를 결합한 뒤, RAG로 관련 지식을 검색하여 LLM에 구조화된 RCA 결과를 생성시킨다.

이 파이프라인은 두 가지 실험 조건을 모두 구현한다:

- **System A (기준선)**: `collector` → `processor` → `llm` (관측 데이터만 사용)
- **System B (제안)**: `collector` → `processor` → `rag` → `llm` (관측 데이터 + GitOps 컨텍스트 + RAG)

## 모듈

| 모듈 | 상태 | 설명 |
|------|------|------|
| `collector/` | **완료** | Prometheus 메트릭, Loki 로그, kubectl 이벤트, GitOps 상태(FluxCD/ArgoCD) 수집 |
| `processor/` | **완료** | 수집된 신호의 전처리; System A/B별 구조화된 LLM 컨텍스트 생성 |
| `llm/` | **완료** | LLM RCA 추론 엔진 — F1~F10 분류, JSON 출력, Anthropic/OpenAI 지원 |
| `rag/` | **완료** | ChromaDB 기반 RAG 파이프라인 — 문서 인제스트, 임베딩, 검색, 컨텍스트 포매팅 |

## collector/ — 신호 수집기

Prometheus, Loki, kubectl, FluxCD/ArgoCD에서 장애 진단 데이터를 수집한다.

| 파일 | 역할 |
|------|------|
| `config.py` | Prometheus/Loki URL, KUBECONFIG 경로, 타임아웃, 네임스페이스 설정 |
| `prometheus.py` | PromQL로 Pod 상태, 재시작, OOM, CPU 쓰로틀, 메모리, 노드, 엔드포인트, PVC, 쿼터, 네트워크 드롭 수집 |
| `loki.py` | LogQL로 Pod 에러 로그, K8s 이벤트 수집 (시간 범위 지정) |
| `kubectl.py` | kubectl JSON 출력 파싱으로 Pod/Event/Service/Node 상태 수집, 비정상 Pod describe |
| `gitops.py` | FluxCD Kustomization/HelmRelease/GitRepository, ArgoCD Application 상태, git 변경 이력 |
| `__init__.py` | `SignalCollector` 통합 클래스: `collect_all()`, `collect_observability_only()`, `collect_gitops_only()` |

```python
# 사용법
from src.collector import SignalCollector
collector = SignalCollector()
all_signals = collector.collect_all(window_minutes=5)        # System B용
obs_signals = collector.collect_observability_only()          # System A용
```

## processor/ — 전처리 모듈

수집된 raw 신호를 LLM이 이해할 수 있는 구조화된 텍스트 컨텍스트로 변환한다.

| 파일 | 역할 |
|------|------|
| `context_builder.py` | `ContextBuilder`: raw dict → `RCAContext` 변환. Pod 상태 요약, 이벤트 포매팅, 메트릭 이상 탐지, 에러 로그 정리, 노드 상태, GitOps 상태를 구조화된 마크다운으로 생성 |

핵심 설계:
- `RCAContext.to_system_a_context()`: 관측 데이터만 포함 (메트릭, 로그, kubectl)
- `RCAContext.to_system_b_context()`: 관측 데이터 + GitOps 상태 + RAG 지식

## llm/ — LLM RCA 추론 엔진

구조화된 컨텍스트를 기반으로 LLM에게 근본 원인 분석을 수행시킨다.

| 파일 | 역할 |
|------|------|
| `rca_engine.py` | `RCAEngine`: F1~F10 장애 유형 분류 프롬프트, JSON 출력 파싱, Anthropic/OpenAI API 호출, 응답시간/토큰 수 기록 |

LLM에게 제공하는 정보:
- F1~F10 장애 유형 목록 + 설명 (분류 가이드)
- 수집된 진단 컨텍스트 (System A 또는 B)
- JSON 출력 형식 지정 (identified_fault_type, root_cause, confidence, remediation 등)

```python
from src.llm import RCAEngine
engine = RCAEngine(model="claude-sonnet-4-6")
result = engine.analyze(context_str, fault_id="F1", trial=1, system="A")
print(result.identified_fault_type, result.confidence)
```

## rag/ — RAG 파이프라인

| 파일 | 역할 |
|------|------|
| `config.py` | 장애 유형 정의(F1~F10), ChromaDB/임베딩/청킹 파라미터 |
| `ingest.py` | 마크다운 → 섹션 기반 청킹 → `all-MiniLM-L6-v2` 임베딩 → ChromaDB 저장 |
| `retriever.py` | 코사인 유사도 검색, 장애 유형 키워드 증강, 카테고리 필터링 |
| `pipeline.py` | RAG + LLM 통합 RCA 파이프라인, JSON 구조화 출력 |

```bash
# 지식베이스 인제스트
python -m src.rag.ingest --reset
```
