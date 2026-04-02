# docs/ — RAG 지식베이스

## 목적

Kubernetes 장애 트러블슈팅 문서 **65건**을 수록한 RAG(Retrieval-Augmented Generation) 지식베이스이다. 이 문서들은 ChromaDB에 벡터 임베딩으로 인제스트되어, RCA 파이프라인이 추론 시 LLM에 도메인 특화 컨텍스트를 제공하는 데 사용된다.

RAG 지식베이스는 **System B(제안 시스템)**의 핵심 구성요소로, LLM이 파라메트릭 지식에만 의존하지 않고 문서화된 장애 패턴, 운영 런북, 클러스터 고유 이슈를 참조하여 근본 원인을 분석할 수 있게 한다.

## 구조

| 디렉토리 | 문서 수 | 설명 |
|----------|---------|------|
| `debugging/` | 20 | Kubernetes 장애 패턴 디버깅 가이드 — 증상, 조사 절차, 해결 방법 (Pod/Node/Network/Storage) |
| `runbooks/` | 20 | 장애 유형별 RCA 절차서(F1~F10) 및 복구 플레이북 (단계별 명령어 포함) |
| `known-issues/` | 25 | 클러스터 구축 중 실제 발생한 이슈 및 Kubernetes 운영상 흔한 함정 |

## 인제스트

문서는 마크다운 섹션 경계를 기준으로 청킹(512자, 64 오버랩)한 후 `all-MiniLM-L6-v2`로 임베딩하여 ChromaDB에 저장한다.

```bash
source .venv/bin/activate
python -m src.rag.ingest --reset    # 전체 재인제스트 (1,243 chunks)
python -m src.rag.ingest            # 증분 인제스트 (기존 건 스킵)
```

## 문서 설계 원칙

1. **이론보다 실행 가능성** — 모든 문서에 구체적인 `kubectl` 명령어 포함, 개념 설명만으로 끝나지 않음
2. **클러스터 고유 컨텍스트** — known-issues에 실제 Cilium/FluxCD/local-path-provisioner 환경에서 겪은 이슈 반영
3. **검색 최적화 구조** — 일관된 마크다운 제목 계층으로 섹션 기반 청킹 시 의미 있는 단위 보장
4. **상호 참조** — 런북은 디버깅 가이드를 참조하고, known-issues는 관련 런북과 연결
