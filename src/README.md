# src/ — RCA 파이프라인 소스코드

## 목적

Kubernetes 클러스터 장애에 대한 자동화된 근본 원인 분석(RCA)을 수행하는 Python 파이프라인이다. 관측 데이터(메트릭, 로그, 이벤트)를 수집하고, 선택적으로 GitOps 컨텍스트를 결합한 뒤, RAG로 관련 지식을 검색하여 LLM에 구조화된 RCA 결과를 생성시킨다.

이 파이프라인은 두 가지 실험 조건을 모두 구현한다:

- **System A (기준선)**: `collector` → `processor` → `llm` (관측 데이터만 사용)
- **System B (제안)**: `collector` → `processor` → `rag` → `llm` (관측 데이터 + GitOps 컨텍스트 + RAG)

## 모듈

| 모듈 | 상태 | 설명 |
|------|------|------|
| `collector/` | 예정 | Prometheus 메트릭, Loki 로그, kubectl 이벤트, GitOps 상태(FluxCD/ArgoCD) 수집 |
| `processor/` | 예정 | 수집된 신호의 전처리 및 특징 추출; LLM에 전달할 구조화된 컨텍스트 생성 |
| `llm/` | 예정 | LLM 추론 래퍼 — 프롬프트 구성, Anthropic/OpenAI API 호출, 구조화된 RCA 결과 파싱 |
| `rag/` | **완료** | ChromaDB 기반 RAG 파이프라인 — 문서 인제스트, 임베딩, 검색, 컨텍스트 포매팅 |

## RAG 모듈 (`src/rag/`)

현재 유일하게 완전 구현된 모듈. RCA 파이프라인에 검색 증강 생성(RAG) 기능을 제공한다.

| 파일 | 역할 |
|------|------|
| `config.py` | 장애 유형 정의(F1~F10), ChromaDB/임베딩/청킹 파라미터 |
| `ingest.py` | 마크다운 → 섹션 기반 청킹 → `all-MiniLM-L6-v2` 임베딩 → ChromaDB 저장 |
| `retriever.py` | 코사인 유사도 검색, 장애 유형 키워드 증강, 카테고리 필터링 |
| `pipeline.py` | RAG + LLM 통합 RCA 파이프라인, JSON 구조화 출력 |

```bash
# 사용법
source .venv/bin/activate
python -m src.rag.ingest --reset          # 문서 ChromaDB 인제스트
python -c "from src.rag import KnowledgeRetriever; r = KnowledgeRetriever(); print(r.query('OOMKilled pod restart'))"
```
