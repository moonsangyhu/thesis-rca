# V4 실험 계획서

> 작성일: 2026-04-07
> 작성자: experiment-planner agent
> 버전: v4 (Context Reranking + Fault Layer Prompt + Harness Simplification)

---

## 1. 실험 목적

V4는 **컨텍스트 구조 최적화**와 **프롬프트 계층화**를 통해 gpt-4o-mini의 RCA 정확도를 개선할 수 있는지 검증한다. V3에서 확인된 세 가지 핵심 문제를 해결한다:

1. **노이즈 > 시그널 문제**: K8s Events(34.9%)가 컨텍스트 상단을 점유하고, 핵심 Metric Anomalies(1.7%)가 하단에 묻혀 "Lost in the Middle" 효과로 놓침
2. **프롬프트 가설 난발**: fault layer 구분 없이 "common failure modes" 나열만 제공하여 모델이 상위 layer가 정상인데도 해당 가설을 생성
3. **죽은 하네스 코드**: Evidence Verification(faithfulness=1.0 상수), System A retry(-12.2pp 역효과)가 성능 저하 유발

### 핵심 질문

1. **컨텍스트 순서 효과**: 핵심 anomaly를 상단에 배치하면 gpt-4o-mini의 진단 정확도가 향상되는가?
2. **Fault Layer 프레임워크**: 계층적 제거 가이드가 가설 난발(예: Node 정상인데 NodeNotReady 진단)을 줄이는가?
3. **하네스 간소화**: 죽은 코드(Evidence Verification) 제거와 System A retry 비활성화가 성능을 유지/개선하는가?

---

## 2. 가설

### 주 가설 (H1): 컨텍스트 리랭킹으로 System B 정확도 향상

V4 System B 정확도가 V3 System B(40%)보다 유의미하게 향상된다.

- **예상 범위**: V4 B = 45-50% (V3 B = 40%, 목표 +5-10pp)
- **근거**:
  - "Lost in the Middle" 연구(Liu et al., 2023)에 따르면 정보 위치가 정확도에 15-20pp 영향
  - V3에서 Metric Anomalies가 1.7%(하단)에 위치 → 상단 이동 시 attention 확보
  - eARCO(2025)에서 프롬프트 최적화만으로 RCA 정확도 21% 개선 보고
- **반증 조건**: V4 B <= 40% (V3 B와 동등 이하)이면 기각

### 부 가설 (H2): Fault Layer 프레임워크로 특정 fault 유형 개선

Layer 기반 제거 가이드로 V3에서 0%인 F4(NodeNotReady), F6-A(NetworkPolicy)의 정확도가 개선된다.

- **예상 범위**: F4 B >= 20% (V3: 0%), F6 A >= 20% (V3: 0%)
- **근거**: V3 raw JSON 분석 결과, F4에서 Node 정상인데 "NodeNotReady" 가설을 생성하는 패턴 관찰. Layer 1 정상 시 "Layer 1 가설을 생성하지 말 것" 지시로 이 패턴 차단 가능
- **반증 조건**: F4 B = 0%이고 F6 A = 0%이면 기각

### 부 가설 (H3): B-A 격차 유지 또는 확대

컨텍스트 리랭킹이 System B에 더 유리하여 B-A 격차가 V3(10pp) 이상 유지된다.

- **예상 범위**: B-A >= 10pp (V3: 10pp)
- **근거**: System B는 GitOps + RAG라는 추가 시그널이 있어, anomaly summary에서 이들을 상단 배치 시 System A 대비 더 큰 이득
- **반증 조건**: B-A < 5pp이면 기각 (GitOps 효과 소실)

### 리스크 가설 (H4, 방어적): 기존 성공 케이스 퇴행 없음

컨텍스트 순서 변경이 V3에서 이미 정확한 케이스(F7 60%, F9 80%)를 퇴행시키지 않는다.

- **감시 기준**: F7 B >= 50%, F9 B >= 70% (V3 대비 -10pp 이내)
- **근거**: K8s Events가 해당 fault의 핵심 단서인 경우, 하단 이동으로 놓칠 가능성 존재
- **완화 전략**: Events를 완전 삭제가 아니라 "Detailed Evidence" 섹션에 유지하여 supporting evidence로 활용

---

## 3. V1-V3 정량 분석 (변경 근거)

### 3.1 버전별 정확도 추세

| 버전 | System A | System B | B-A | Wilcoxon p | 주요 변경 |
|------|----------|----------|-----|------------|-----------|
| V1 | 30% (15/50) | 84% (42/50) | +54pp | - | 힌트+단순 |
| V2 | 26% (13/50) | 42% (21/50) | +16pp | 0.002 (V1B vs V2B) | 힌트제거+CoT |
| V3 | 30% (15/50) | 40% (20/50) | +10pp | 1.000 (V2B vs V3B) | Harness 추가 |

**핵심 관찰**: V2 -> V3에서 Harness 추가는 통계적으로 무효과(p=1.000). Harness 방향이 아닌 **입력 품질(컨텍스트/프롬프트)** 개선이 필요.

### 3.2 V3 Fault별 상세 분석 — 개선 타겟 선정

| Fault | V3_A | V3_B | 문제 진단 | V4 개선 전략 | 기대 효과 |
|-------|------|------|-----------|-------------|----------|
| F1 (OOM) | 20% | 20% | Metric anomaly 하단 묻힘, 다른 pod 이슈에 fixation | Anomaly summary 상단 배치 | B 40%+ |
| F2 (Crash) | 20% | 20% | CrashLoopBackOff가 Events에 있으나 verbose | Anomaly summary에 "pod_status=CrashLoop" 명시 | B 40%+ |
| F3 (Image) | 40% | 20% | B가 A보다 낮음 — GitOps 노이즈가 오도 | GitOps correlation 필터링 | B >= A (40%) |
| F4 (Node) | 0% | 0% | 수집 윈도우 내 Node 상태 반영 부족 | Layer 1 우선 판별, Node anomaly 강조 | B 20%+ |
| F5 (PVC) | 40% | 60% | 양호 — PVC Pending이 명확한 시그널 | 유지 | B 60%+ |
| F6 (Net) | 0% | 40% | System A에서 network drops 시그널 놓침 | Network anomaly 상단 배치 | A 20%+ |
| F7 (CPU) | 60% | 60% | 양호 — CPU throttle 메트릭 명확 | 유지 (퇴행 감시) | B 60%+ |
| F8 (Svc) | 20% | 40% | endpoints=0이 metric anomaly에 있으나 하단 | endpoints=0 상단 배치 | B 60%+ |
| F9 (Secret) | 60% | 80% | 양호 — CreateContainerConfigError 명확 | 유지 (퇴행 감시) | B 80%+ |
| F10 (Quota) | 40% | 60% | quota 시그널 하단, 잡다한 이벤트에 묻힘 | Quota anomaly 상단 배치 | B 60%+ |

### 3.3 V3 컨텍스트 구조 분석 (raw JSON 기반)

V3 System B 평균 컨텍스트 6,900자:

| 섹션 | 비율 | 위치 | 역할 |
|------|------|------|------|
| Pod Status | 9.6% (660자) | 1위 (상단) | 정상 pod 포함, verbose |
| K8s Events | 34.9% (2,400자) | 2위 | 반복적, count=1 이벤트 다수 |
| Metric Anomalies | 1.7% (119자) | 3위 (중간) | **핵심 진단 시그널** — 하단 묻힘 |
| Error Logs | 3.0% (207자) | 4위 | 유용하나 중간 위치 |
| Node Status | 4.0% (276자) | 5위 | 정상 노드 정보 포함 |
| GitOps Status | 0.4% (30자) | 6위 | 시간적 상관 없는 경우 레드헤링 |
| Git Changes | 0.9% (62자) | 7위 | 정보량 미미 |
| RAG KB | 2.4% (166자) | 8위 (하단) | fault 관련 지식 |

**문제**: gpt-4o-mini는 left-to-right 처리에서 상단 정보에 더 강한 attention 할당. 핵심 Metric Anomalies(1.7%)가 verbose K8s Events(34.9%) 뒤에 위치하여 "Lost in the Middle" 효과 발생.

---

## 4. 변경 사항 상세

### 변경 1: 컨텍스트 리랭킹 (`src/processor/context_builder.py`)

**현재 순서 (V3)**:
```
Pod Status → K8s Events → Metric Anomalies → Error Logs → Node Status → GitOps → Git Changes → RAG
```

**V4 순서**:
```
## ANOMALY SUMMARY (최상단, 핵심 이상만)
- 비정상 Pod: [phase != Running 또는 ready=false인 pod만, 정상 pod 제외]
- Metric 이상: [severity 순 정렬: OOM > Quota > Throttle > Endpoints=0 > PVC > NetworkDrops]
- Node 이상: [NotReady 노드만, 정상 노드 제외]

## CORRELATED CHANGES (시간적 상관이 있는 GitOps/Git 변경만)
- GitOps: [FluxCD/ArgoCD NOT READY 상태만]
- Git Changes: [최근 커밋 변경 파일 중 fault와 관련된 것만]

## KNOWLEDGE BASE (RAG)
- [기존 RAG 컨텍스트 유지]

## DETAILED EVIDENCE (하단, supporting)
- K8s Events: [기존 이벤트, 단 상위 15개만 — 30개에서 축소]
- Error Logs: [기존 로그]
- Full Pod Status: [전체 pod 상태]
- Full Node Status: [전체 노드 상태]
```

**구체적 코드 변경 (`context_builder.py`)**:

1. `to_system_a_context()` 수정:
   - 새 메서드 `_build_anomaly_summary()` 추가: 비정상 pod만 필터링, metric anomalies를 severity 순 정렬, NotReady 노드만 포함
   - 순서: Anomaly Summary → Error Logs → K8s Events(상위 15개) → Full Pod Status → Full Node Status

2. `to_system_b_context()` 수정:
   - 순서: Anomaly Summary → Correlated Changes(GitOps NOT READY만) → RAG KB → Error Logs → K8s Events → Full Pod/Node Status

3. `_build_pod_summary()` 분리:
   - `_build_abnormal_pods()`: phase != Running 또는 container not ready인 pod만 반환
   - `_build_full_pod_status()`: 전체 pod 상태 (기존 동작, Detailed Evidence용)

4. `_build_events()` 수정:
   - `max_events` 파라미터 추가 (기본값 15, 기존 30에서 축소)
   - 중복 이벤트(같은 reason+object) 병합, count 합산

5. `_build_node_status()` 분리:
   - `_build_abnormal_nodes()`: NotReady 노드만 반환
   - `_build_full_node_status()`: 전체 노드 상태

6. `_build_gitops_status()` 수정:
   - NOT READY 상태인 kustomization/helmrelease/application만 포함
   - Ready 상태는 제외 (노이즈 제거)

**예상 효과**:
- Anomaly Summary가 전체 컨텍스트의 10-15% 차지 (기존 Metric Anomalies 1.7%에서 확대)
- K8s Events가 상단 → 하단으로 이동, 15개 제한으로 34.9% → ~15%로 축소
- 정상 pod/node 정보 제거로 전체 컨텍스트 길이 20-30% 감소

### 변경 2: Fault Layer 프롬프트 (`experiments/v4/prompts.py`)

**V3 프롬프트 Step 2 (현재)**:
```
Step 2 - Hypothesis Generation: ... Consider common Kubernetes failure modes such as
resource exhaustion (memory, CPU), configuration errors (secrets, configmaps, selectors),
network issues (policies, DNS, connectivity), storage problems (PVC, volumes), ...
```

**V4 프롬프트 Step 2 (변경)**:
```
Step 0 - Fault Layer Classification (BEFORE generating hypotheses):
Classify the fault into one of three layers. Check each layer in order.
ONLY generate hypotheses for the identified layer.

Layer 1 -- Infrastructure/Node:
  Check: Any node NotReady? DiskPressure? MemoryPressure? kubelet issues?
  If YES -> Focus hypotheses on node-level causes.
  If ALL nodes are Ready and healthy -> SKIP Layer 1 entirely. Do NOT hypothesize
  about node issues.

Layer 2 -- Deployment/Manifest:
  Check: Any pod in ImagePullBackOff? CreateContainerConfigError? PVC Pending?
  Service endpoints=0? ResourceQuota exceeded?
  If YES -> Focus hypotheses on manifest/configuration causes.
  If no manifest-level anomalies -> SKIP Layer 2. Do NOT hypothesize about
  image, secret, or selector issues unless there is direct evidence.

Layer 3 -- Runtime/Network:
  Check: Pod Running but unhealthy/slow? CrashLoopBackOff? CPU throttling?
  NetworkPolicy drops? gRPC deadline exceeded?
  -> Focus hypotheses on runtime behavior or network connectivity.

CRITICAL RULE: If an upper layer shows NO anomalies, do NOT generate hypotheses
for that layer. For example, if all nodes are Ready, never suggest "NodeNotReady"
as a hypothesis.
```

**V4 프롬프트의 나머지 구조**:
- Step 1 (Signal Inventory): V3와 동일하되, "ANOMALY SUMMARY 섹션을 먼저 읽어라" 지시 추가
- Step 2: 위의 Layer Classification으로 대체
- Step 3-5: V3와 동일 (Evidence Matching, Differential, Confidence)
- Evaluator, Retry: V3와 동일 (System B에서만 retry 활성화)

### 변경 3: 하네스 간소화 (`experiments/v4/engine.py`, `experiments/v4/config.py`)

| 항목 | V3 | V4 | 근거 |
|------|----|----|------|
| Evidence Verification | keyword matching (faithfulness 전부 1.0) | **제거** | V3 100건 전부 1.0 — 정보량 0, 코드 복잡성만 증가 |
| Evaluator | 유지 | 유지 | System B retry의 전제 조건 |
| Retry (System A) | 활성 (-12.2pp 역효과) | **비활성** | V3 데이터: retry 시 A 정확도 34.4% → 22.2% (-12.2pp) |
| Retry (System B) | 활성 (+28.8pp 효과) | **유지** | V3 데이터: retry 시 B 정확도 25.0% → 53.8% (+28.8pp) |
| MAX_RETRIES | 2 | 2 | V3 동일 |

**config.py 변경**:
```python
RETRY_ENABLED_A = False  # System A retry 비활성화
RETRY_ENABLED_B = True   # System B retry 유지
```

**engine.py 변경**:
- `_verify_evidence()` 메서드 삭제
- `analyze()` 내 evidence verification 호출 제거
- `faithfulness_score` 필드는 CSV에서 유지하되 0.0 고정 (호환성)
- retry 조건에 `system == "B"` 체크 추가

### 변경 4: V4 모듈 생성

V3를 복사하여 V4 독립 모듈 생성:

```
experiments/v4/
  __init__.py
  config.py    -- V4 경로, RETRY_ENABLED_A/B 플래그
  prompts.py   -- Fault Layer 프롬프트
  engine.py    -- 간소화된 하네스
  run.py       -- 진입점 (v3 기반, 모듈 참조만 변경)
```

---

## 5. 수정 대상 파일 체크리스트

### 5.1 공유 코드 수정 (모든 버전에 영향)

| # | 파일 | 변경 내용 | 주의사항 |
|---|------|----------|---------|
| 1 | `src/processor/context_builder.py` | 컨텍스트 리랭킹 (상세 4.1절) | **V1-V3에도 영향** — 기존 버전의 재현성 확보 필요. V4 전용 분기 또는 버전 파라미터 추가 권장 |

**대안 A**: `context_builder.py`에 `version` 파라미터 추가하여 V4 전용 순서 적용 (기존 버전 호환)
**대안 B**: `experiments/v4/context_builder.py`로 V4 전용 빌더 생성 (코드 중복이나 기존 버전 무영향)

**권장**: 대안 B — V4 전용 `context_builder.py` 생성. 이유:
1. 기존 V1-V3 결과 재현 가능성 보장
2. 수정 범위가 V4 모듈 내로 한정
3. 코드 중복이 있으나, 실험 버전별 독립성이 더 중요

### 5.2 V4 모듈 신규 생성

| # | 파일 | 내용 |
|---|------|------|
| 1 | `experiments/v4/__init__.py` | 빈 파일 |
| 2 | `experiments/v4/config.py` | V4 경로, RETRY 플래그, CSV 헤더 |
| 3 | `experiments/v4/prompts.py` | Fault Layer 프롬프트 + 기존 Evaluator/Retry |
| 4 | `experiments/v4/engine.py` | Evidence Verification 제거, System A retry 비활성화 |
| 5 | `experiments/v4/run.py` | V3 run.py 기반, V4 모듈 참조 |
| 6 | `experiments/v4/context_builder.py` | 리랭킹된 컨텍스트 빌더 |

### 5.3 공유 Runner 수정 (선택적)

| # | 파일 | 변경 | 필요 여부 |
|---|------|------|----------|
| 1 | `experiments/shared/runner.py` | V4 context_builder 사용 분기 | 필요 — TrialRunner가 builder를 주입받으므로 run.py에서 V4 빌더를 주입하면 됨. Runner 자체 수정 불필요 |

---

## 6. 모델/프로바이더

| 항목 | 값 | 근거 |
|------|----|------|
| 모델 | `gpt-4o-mini` | **고정 제약** — V1-V4 전체 동일 모델로 프레임워크 효과만 분리 측정 |
| 프로바이더 | `openai` | V1-V3 동일 |
| MAX_TOKENS | 2048 | V3 동일 — evidence chain + bilingual 출력에 충분 |
| MAX_RETRIES | 2 | V3 동일 (System B에서만 적용) |

---

## 7. 실험 파라미터

### 7.1 실험 범위

| 항목 | 값 |
|------|----|
| Fault types | F1-F10 전체 (10종) |
| Trials per fault | 5 |
| Systems per trial | A + B |
| 총 trial 수 | 50 (= 10 x 5) |
| 총 RCA 실행 수 | 100 (= 50 x 2 systems) |

### 7.2 Cooldown 전략 (V3 동일)

| 구간 | 대기 시간 | 추가 검증 |
|------|----------|-----------|
| Trial 간 | 60초 | + health check 3회 x 30초 |
| Fault 간 | 900초 (15분) | + Failed pod 삭제 + health check 3회 x 60초 |

### 7.3 RAG 파라미터 (V3 동일)

| 항목 | 값 |
|------|----|
| TOP_K | 5 |
| SCORE_THRESHOLD | 0.3 |
| EMBEDDING_MODEL | all-MiniLM-L6-v2 |

### 7.4 수집 윈도우 (V3 동일)

| 항목 | 값 |
|------|----|
| COLLECTION_WINDOW | 300초 (5분) |
| INJECTION_WAIT | fault별 상이 (60-180초) |

---

## 8. 리스크 분석

### 8.1 기존 성공 케이스 퇴행 (중간 리스크)

- **위험**: K8s Events를 하단으로 이동하면, Events가 핵심 단서인 fault (F2 CrashLoopBackOff, F3 ImagePullBackOff)에서 정확도 하락 가능
- **확률**: 중간 — F2, F3는 pod status에서도 CrashLoopBackOff/ImagePullBackOff를 확인 가능하므로 Anomaly Summary에 반영됨
- **완화**: Anomaly Summary에 "비정상 Pod: pod_name (CrashLoopBackOff)" 형태로 pod waiting reason 포함
- **감시 지표**: F2 B >= 15%, F3 B >= 15% (V3 대비 -5pp 이내)

### 8.2 Anomaly Summary 과소 포함 (낮은 리스크)

- **위험**: `_build_abnormal_pods()`가 비정상 조건을 너무 좁게 정의하여 fault 관련 pod를 누락
- **완화**: "phase != Running" 또는 "any container not ready" 또는 "restarts > 0 in last 5min" 기준 적용 — 넓은 필터
- **검증**: dry-run에서 각 fault별 Anomaly Summary 내용 확인

### 8.3 GitOps 필터링 과잉 (낮은 리스크)

- **위험**: Ready 상태 GitOps 정보를 제거하면, "최근 성공 배포"라는 유용한 맥락도 사라짐
- **반론**: V3 분석에서 GitOps Ready 상태 정보는 RCA에 기여한 사례가 0건. NOT READY만 유의미
- **완화**: NOT READY일 때만 표시하되, "FluxCD 마지막 성공 동기화 시각" 1줄은 유지

### 8.4 프롬프트 과제약 (중간 리스크)

- **위험**: "상위 layer가 정상이면 해당 layer 가설을 생성하지 말 것" 지시가 too rigid하여, 복합 장애(예: node 문제 + pod 문제 동시) 시 상위 layer를 무시할 수 있음
- **확률**: 낮음 — 본 실험의 fault는 단일 fault type (복합 장애 아님)
- **완화**: "상위 layer에 anomaly가 없으면" 조건을 명시하여, anomaly가 있는 경우는 자유롭게 가설 생성 가능

### 8.5 System A retry 비활성화 부작용 (매우 낮은 리스크)

- **위험**: System A retry가 특정 fault에서는 효과적일 수 있음
- **반론**: V3 전체 데이터에서 System A retry는 -12.2pp 역효과. Fault별로도 retry로 정답 전환된 케이스가 A에서는 극소수
- **완화**: V4 결과에서 System A retry 활성화 시뮬레이션 (사후 분석)은 불가하므로, 이 결정은 V3 데이터 기반 확정

---

## 9. 통계 검정 계획

### 9.1 주요 비교

| 비교 | 검정 방법 | 유의수준 | 목적 |
|------|-----------|---------|------|
| V4 B vs V3 B (fault별) | Wilcoxon signed-rank test | alpha=0.05 | H1 검증 — 컨텍스트 최적화 효과 |
| V4 A vs V4 B (fault별) | Wilcoxon signed-rank test | alpha=0.05 | GitOps 효과 유지 확인 |
| V4 A vs V4 B (trial별) | McNemar test | alpha=0.05 | 개별 trial 수준 paired 비교 |

### 9.2 보조 분석

| 분석 | 방법 | 목적 |
|------|------|------|
| F4 개선 | Fisher exact test (V3 vs V4, B만) | H2 검증 — 특정 fault 개선 |
| 퇴행 검사 | V3 성공 케이스의 V4 정답 유지율 | H4 검증 — 기존 성공 보존 |
| Retry 효과 (B) | retry=0 vs retry>0 정확도 비교 | 하네스 간소화 후에도 B retry 효과 유지 확인 |
| 컨텍스트 길이 변화 | V3 vs V4 prompt_tokens 비교 | 컨텍스트 압축 효과 정량화 |
| Effect size | Cohen's d 또는 r (from Wilcoxon) | 효과 크기 보고 (논문용) |

### 9.3 다중 비교 보정

- 주요 비교 3건에 대해 Bonferroni 보정 적용 (alpha = 0.05/3 = 0.017)
- 보조 분석은 탐색적으로 보고 (보정 미적용, 단 탐색적임을 명시)

---

## 10. 인프라 체크리스트

```
[ ] SSH 터널 활성화 (K8s API, Prometheus, Loki) — /lab-tunnel 실행
[ ] kubectl get nodes — 모든 노드 Ready
[ ] kubectl get pods -n boutique — 12개 이상 Running
[ ] Prometheus (localhost:9090) 응답 확인
[ ] Loki (localhost:3100) 응답 확인
[ ] .env 파일에 OPENAI_API_KEY 설정 확인
[ ] KUBECONFIG 환경변수 확인 (~/.kube/config-k8s-lab)
[ ] RAG ChromaDB 빌드 확인 (python -m src.rag.ingest --reset)
[ ] V4 코드 수정 완료 (code-reviewer 확인)
[ ] dry-run 테스트 통과 (python -m experiments.v4.run --dry-run)
[ ] 디스크 여유 공간 확인 (raw JSON 100개 생성 예상)
[ ] Error/Evicted pod 잔여물 제거
[ ] V3 raw 데이터 백업 확인 (results/backup/)
```

---

## 11. 실행 명령어

### 11.1 사전 준비

```bash
# 1. 환경 활성화
cd /Users/yumunsang/Documents/thesis-rca
source .venv/bin/activate

# 2. SSH 터널 (별도 터미널) — /lab-tunnel 스킬 사용

# 3. RAG KB 확인/재빌드
python -m src.rag.ingest --reset

# 4. dry-run 테스트 (V4 컨텍스트 빌더 동작 확인)
python -m experiments.v4.run --dry-run
```

### 11.2 전체 실험 실행

```bash
nohup python -m experiments.v4.run \
  --model gpt-4o-mini \
  --provider openai \
  --cooldown 900 \
  > results/experiment_v4_nohup.log 2>&1 &

echo $! > results/experiment_v4.pid
```

### 11.3 모니터링

```bash
tail -f results/experiment_v4.log
grep "Progress:" results/experiment_v4.log | tail -5
wc -l results/experiment_results_v4.csv
```

### 11.4 중단 후 재개

```bash
python -m experiments.v4.run \
  --model gpt-4o-mini \
  --provider openai \
  --cooldown 900 \
  --resume
```

### 11.5 단일 fault/trial 재실행

```bash
python -m experiments.v4.run --fault F1 --trial 1 --model gpt-4o-mini --provider openai
```

---

## 12. 예상 소요 시간 및 비용

### 12.1 시간 추정

V4는 Evidence Verification 제거 + System A retry 비활성화로 V3 대비 LLM 호출 감소.

| 시나리오 | V3 호출 수 | V4 호출 수 | 변화 |
|----------|------------|------------|------|
| Retry 없음 (A+B) | 6회 (gen_A + eval_A + judge_A + gen_B + eval_B + judge_B) | 5회 (gen_A + judge_A + gen_B + eval_B + judge_B) | -1회 (eval_A 유지하되 retry 안 함) |
| B retry 1회 | 8회 | 7회 | -1회 |
| 최대 (B retry 2회) | 14회 | 9회 | -5회 |

**참고**: System A에서 Evaluator 자체는 유지 (eval_overall_score 데이터 수집용), retry만 비활성화.

| 항목 | 시간 |
|------|------|
| 50 trials x 250초 | ~3.5시간 |
| Trial 간 cooldown (40 x 60초) | ~0.7시간 |
| Trial 간 health check (40 x 90초) | ~1시간 |
| Fault 간 cooldown (9 x 900초) | ~2.3시간 |
| Fault 간 health check (9 x 180초) | ~0.5시간 |
| **총 예상 시간** | **~8시간** |

V3 실제 소요시간(5시간 42분)을 참고하면, V4는 **6-8시간** 예상.

### 12.2 비용 추정

gpt-4o-mini 요금: Input $0.15/1M, Output $0.60/1M

| 항목 | V3 실측 | V4 예상 | 변화 |
|------|---------|---------|------|
| 평균 prompt tokens/trial | 4,914 | ~4,200 (컨텍스트 축소 + A retry 제거) | -15% |
| 평균 completion tokens/trial | 1,141 | ~1,000 (A retry 제거) | -12% |
| 총 비용 | $0.142 | **~$0.12** | -15% |

비용은 $0.12-0.15 수준으로 V3와 유사하며, 무시 가능한 수준.

---

## 13. 성공 기준

### 13.1 실험 완료 기준

- [ ] `experiment_results_v4.csv`에 100행 (50 trials x 2 systems) 기록
- [ ] `results/raw/` (또는 v4 전용 디렉토리)에 100개 JSON 파일 생성
- [ ] error 컬럼이 비어있는 행이 95% 이상
- [ ] V4 고유 필드 (eval_*, retry_count) 유효값 기록

### 13.2 가설 검증 기준

| 가설 | 성공 | 부분 성공 | 실패 |
|------|------|----------|------|
| H1 (B 정확도) | V4 B >= 48% (Wilcoxon p < 0.05) | V4 B = 42-47% (개선 있으나 통계적 비유의) | V4 B <= 40% |
| H2 (F4/F6 개선) | F4 B >= 20% AND F6 A >= 20% | 둘 중 하나만 개선 | 둘 다 0% |
| H3 (B-A 격차) | B-A >= 12pp | B-A = 8-11pp | B-A < 5pp |
| H4 (퇴행 없음) | F7 B >= 50% AND F9 B >= 70% | 하나만 미달 | 둘 다 미달 |

### 13.3 논문 기여 판단

| 결과 | 해석 | 논문 기여 |
|------|------|-----------|
| H1 성공 (p < 0.05) | 컨텍스트 구조가 gpt-4o-mini RCA 정확도에 유의미한 영향 | **핵심 기여** — "Context Engineering for LLM-based RCA" |
| H1 부분 성공 | 방향은 맞으나 통계적 검정력 부족 (n=10 fault types) | 탐색적 발견으로 보고, 추후 대규모 실험 제안 |
| H1+H2 모두 실패 | gpt-4o-mini의 구조적 한계 — 컨텍스트/프롬프트로는 불충분 | **부정적 결과이나 유의미** — 모델 크기가 RCA에 미치는 병목 분석 |
| H4 실패 (퇴행 발생) | 컨텍스트 순서 변경의 양날의 검 효과 | 트레이드오프 분석 보고 — "what you gain, what you lose" |

---

## 14. 이전 실험 대비 변경점 요약

| 항목 | V1 | V2 | V3 | V4 |
|------|----|----|----|----|
| 힌트 | 포함 | 제거 | 제거 | 제거 |
| 프롬프트 | 단순 | CoT | CoT + evidence chain | **CoT + Fault Layer** |
| 컨텍스트 순서 | 기본 | 기본 | 기본 | **Anomaly-first** |
| 정상 pod/node | 포함 | 포함 | 포함 | **제외 (Anomaly Summary)** |
| K8s Events 위치 | 상단 | 상단 | 상단 | **하단 (supporting)** |
| Evidence Verification | 없음 | 없음 | keyword matching | **제거** |
| Evaluator | 없음 | 없음 | 4차원 평가 | 유지 |
| Retry (System A) | 없음 | 없음 | 활성 | **비활성** |
| Retry (System B) | 없음 | 없음 | 활성 | 유지 |
| 모델 | gpt-4o-mini | gpt-4o-mini | gpt-4o-mini | gpt-4o-mini |
| System A 정확도 | 30% | 26% | 30% | **?** |
| System B 정확도 | 84% | 42% | 40% | **?** |

---

## 15. 실험 일정 (권장)

| 단계 | 예상 소요 | 담당 |
|------|----------|------|
| V4 코드 구현 (context_builder, prompts, engine, config, run) | 1-2시간 | @code-reviewer |
| dry-run + 단건 테스트 (F1 t1) | 30분 | @experiment |
| 전체 실험 실행 (F1-F10) | 6-8시간 | @experiment (nohup) |
| 결과 분석 리포트 | 1시간 | @results-writer |
| **총 소요** | **~9-12시간** | |

---

## 16. 참고 문헌

- Liu et al. (2023). "Lost in the Middle: How Language Models Use Long Contexts." arXiv:2307.03172
- eARCO (2025). "Efficient Automated Root Cause Analysis with Prompt Optimization." arXiv:2504.11505
- MIT (2025). "Unpacking the bias of large language models" — position bias의 근본 원인(causal masking + RoPE decay) 분석
