# 심층 분석: V8 실험 설계를 위한 개선점 도출

> 분석일: 2026-04-09
> 분석 대상: V3, V6, V7 실험 결과 (V4/V5는 실패 실험으로 참조만)
> 목적: V8 실험의 개선 가설 수립을 위한 데이터 기반 근거 확보

## 1. 오답 패턴 분석

### V7 오답 빈도 (총 84건: A=47, B=37)

**System A 주요 오답 유형:**
| 오답 분류 | 빈도 | 관련 fault |
|-----------|------|-----------|
| CrashLoopBackOff | 11건 | F10, F11, F12에서 집중 |
| Service Endpoint Fault/Issue | 13건 | F4, F5, F6에서 집중 |
| 기타 (Disk Pressure 등) | 23건 | 분산 |

**System B 주요 오답 유형:**
| 오답 분류 | 빈도 | 관련 fault |
|-----------|------|-----------|
| CrashLoopBackOff | 9건 | F11, F12 전체 (10/10) 중 대부분 |
| Service Endpoint 계열 | 8건 | F4에서 집중 |
| 기타 | 20건 | 분산 |

### A/B 공통 오답: 36건 (전체 오답의 97%)
- **F4 전체 5건**: A/B 모두 "Service Endpoint Fault" → 노드 장애 신호 부재
- **F11 전체 5건**: A/B 모두 "CrashLoopBackOff" → 클러스터 오염 + 네트워크 메트릭 부재
- **F12 전체 5건**: A/B 모두 "CrashLoopBackOff" → 동일
- **핵심 발견**: B만 정답인 trial은 11건뿐이고, A만 정답은 1건. 대부분의 개선은 B의 추가 컨텍스트가 결정적.

### 오염 패턴 (Critical)
F11/F12 raw JSON 분석 결과, 모든 trial에서 동일한 오염 신호 발견:
- `shippingservice-7d866b6f4d-xkv66: CrashLoopBackOff restarts=28~40+` (이전 fault 복구 잔류)
- `frontend: 0 endpoints` (이전 fault 복구 잔류)
- **실제 네트워크 장애 신호: 0건** (지연/손실 메트릭이 수집 파이프라인에 없음)

## 2. 버전 간 변화 추적

| Fault | V3-A | V3-B | V6-A | V6-B | V7-A | V7-B | V3→V7 B 변화 |
|-------|------|------|------|------|------|------|-------------|
| F1 OOMKill | 20% | 20% | 20% | 20% | 40% | 20% | FLAT |
| F2 CrashLoop | 20% | 20% | 20% | 60% | 0% | 100% | **+80pp** |
| F3 ImagePull | 40% | 20% | 40% | 40% | 60% | 60% | **+40pp** |
| F4 NodeNotReady | 0% | 0% | 0% | 0% | 0% | 0% | FLAT (0%) |
| F5 PVCPending | 40% | 60% | 20% | 20% | 40% | 40% | **-20pp** |
| F6 NetworkPolicy | 0% | 40% | 0% | 0% | 0% | 40% | FLAT |
| F7 CPUThrottle | 60% | 60% | 40% | 100% | 40% | 60% | FLAT |
| F8 SvcEndpoint | 20% | 40% | 20% | 60% | 0% | 40% | FLAT |
| F9 SecretConfigMap | 60% | 80% | 40% | 20% | 40% | 40% | **-40pp** |
| F10 ResourceQuota | 40% | 60% | 60% | 60% | 40% | 60% | FLAT |
| F11 NetworkDelay | - | - | - | - | 0% | 0% | NEW |
| F12 NetworkLoss | - | - | - | - | 0% | 0% | NEW |
| **F1-F10 합계** | **30%** | **40%** | **26%** | **38%** | **26%** | **46%** | **+6pp** |

### 주요 관찰
- **F2 CrashLoop**: V3 20% → V7 100% (B). SOP-guided 프롬프트의 최대 수혜자.
- **F9 SecretConfigMap**: V3 80% → V7 40% (B). V6 Step 3 흡수 문제가 V7에서도 완전 해소되지 않음.
- **F5 PVCPending**: V3 60% → V7 40% (B). 유사 퇴행.
- **F4/F11/F12**: 모든 버전에서 0%. 구조적 신호 부재 문제.

## 3. 컨텍스트 구조 분석

### 컨텍스트 길이 vs 정확도
- **정답 trial**: 평균 ctx_len = **3,886 chars** (n=36)
- **오답 trial**: 평균 ctx_len = **2,542 chars** (n=84)
- 정답 trial이 ~53% 더 긴 컨텍스트. 더 많은 신호 → 더 정확한 진단.

### F11 t1 (B) 컨텍스트 내용 (1,920 chars)
```
Pod Status: 모두 Running (shippingservice CrashLoopBackOff 제외)
Events: shippingservice BackOff (count=553) — 이전 fault 잔류물
Metric Anomalies: "Services with 0 endpoints: frontend" — 유일한 메트릭 이상
Error Logs: NONE
Node Status: 모두 Ready
```
**네트워크 지연/손실 관련 신호: 완전 부재**. LLM이 CrashLoopBackOff을 진단하는 것은 합리적 — 그것이 유일하게 이상한 신호이므로.

### F4 t1 (B) 컨텍스트 내용 (4,479 chars)
```
Pod Status: 모두 Running (12개, 이미 재스케줄링 완료)
Events: NONE
Metric Anomalies: "Services with 0 endpoints: frontend"
Node Status: 모두 Ready (kubelet 이미 복구됨)
```
**노드 장애 관련 신호: 완전 부재**. 수집 시점에 이미 복구되어 모든 노드 Ready.

## 4. Evaluator 효과 분석

### Retry 분석 (V7)
| System | retry=0 | retry=1 | retry=2 |
|--------|---------|---------|---------|
| A | 6/29 = 21% | 6/14 = **43%** | 1/17 = 6% |
| B | 14/33 = **42%** | 2/11 = 18% | 7/16 = **44%** |

- retry=1에서 A가 43%로 개선되나, retry=2에서 6%로 급락 → 과도한 retry는 역효과
- B는 retry=0 (42%)과 retry=2 (44%)에서 유사 → retry 효과 불분명

### Evaluator 점수 vs 정확도
| System | 정답 평균 | 오답 평균 | 차이 |
|--------|----------|----------|------|
| A | 8.25 | 7.95 | +0.30 |
| B | 8.01 | 7.94 | +0.07 |

**Evaluator 판별력 거의 없음** (8점대에 집중, 정답/오답 차이 < 0.3). V3에서도 동일 문제 확인.

## 5. GitOps 컨텍스트 효과 분석

### B만 정답인 trial (11건)
| Fault | Trial | A의 오답 | B의 정답 | GitOps 기여 |
|-------|-------|---------|---------|-----------|
| F2 t1-t5 | 5건 | Readiness/Service/Container | CrashLoopBackOff | RAG 런북이 CrashLoop 패턴 인식 지원 |
| F6 t1 | 1건 | Service Endpoint Fault | Service Endpoint Fault | GitOps manifest diff로 deny-all 정책 확인 |
| F6 t5 | 1건 | Service Endpoint Fault | NetworkPolicy Block | GitOps diff에서 NetworkPolicy 변경 확인 |
| F7 t2 | 1건 | Readiness/Liveness | CPU Throttle | RAG 런북이 CPU throttle 패턴 보강 |
| F8 t3,t4 | 2건 | CPU Throttle/Readiness | Service Endpoint Misconfig | GitOps diff에서 selector/probe 변경 확인 |
| F10 t1 | 1건 | CrashLoop+ResourceQuota | Resource Quota Exceeded | RAG가 quota 패턴 제공 |

### A만 정답인 trial (1건)
- F1 t1: A="Resource Exhaustion" (정답) vs B="CPU Throttling" (오답)
  → B의 RAG 컨텍스트가 오히려 CPU 방향으로 오도

### 결론
- **GitOps/RAG 효과는 manifest 변경 기반 fault에서 강력**: F2(런북), F6(diff), F8(diff), F10(런북)
- **B 퇴행 최소**: 1건만 A→B로 퇴행 (F1 t1)
- **F11/F12에 RAG 미등록 → B가 A와 동일하게 작동** (RAG fallback 없음)

## 6. 참조 기법 (인터넷 서칭 + 학습 데이터)

### 6-1. SynergyRCA — StateGraph + LLM (arxiv:2506.02490)
- Kubernetes RCA에 그래프 기반 컨텍스트 + LLM 결합
- StateGraph로 엔티티 간 공간/시간 관계 포착 → MetaGraph로 RCA 수행
- **적용 가능성**: 우리 실험은 단일 프롬프트 기반이라 그래프 구축이 범위 밖. 단, "엔티티 관계를 컨텍스트에 포함"하는 아이디어는 참조 가능.

### 6-2. gRPC Observability Metrics (grpc.io/docs)
- `grpc.server.call.duration` — 서버 측 호출 지연 히스토그램
- `grpc.client.attempt.duration` — 클라이언트 측 시도별 지연
- OpenTelemetry 기반 표준 메트릭
- **적용 가능성**: Online Boutique가 gRPC 사용 → 이 메트릭이 존재하면 F11 진단에 직접 활용 가능

### 6-3. Network Observability for AIOps (Red Hat, 2025)
- Prometheus + synthetic probes로 packet loss, TLS handshake, response codes 측정
- `node_network_transmit_errs_total`, `node_network_receive_errs_total` 메트릭
- **적용 가능성**: 이미 node-exporter에서 수집 가능한 메트릭. Prometheus 쿼리 추가만으로 활용 가능.

### 6-4. Signal Enrichment Principle (일반 원칙)
- RAG 효과 = f(검색 관련성 × 신호 존재 여부)
- RAG에 문서가 있어도, 실제 컨텍스트에 관련 신호가 없으면 LLM이 활용 불가
- **적용**: F11/F12는 RAG 등록 + 신호 수집 + 런북 3가지 모두 필요 (어느 하나만 부족해도 효과 없음)

## 7. 개선 가설

### 가설 a: 네트워크 신호 보강 (Network Signal Enrichment) — **우선순위 1**

**변경 변수**: Prometheus 네트워크 메트릭 4종 추가 + F11/F12 RAG 등록 + F11/F12 런북 작성
**근거**:
- 데이터 근거: F11 전체 10 trial, F12 전체 10 trial = 20건 모두 0%. Raw context에 네트워크 관련 메트릭 0건. RAG 로그에 `Unknown fault type: F11/F12` 오류 확인.
- 문헌 근거: gRPC observability 표준 메트릭(`grpc.server.call.duration`), node-exporter 네트워크 메트릭(`node_network_transmit_errs_total`) — 모두 표준 Prometheus 수집 대상
**메커니즘**: 
1. Prometheus에 request latency p95/p99, gRPC error rate, node network errors, TCP retransmission 메트릭 추가
2. 컨텍스트에 "p95 latency: 1.2s", "gRPC DeadlineExceeded rate=0.5/s" 등 명시적 네트워크 이상 신호 포함
3. RAG에 F11/F12 등록 → B 시스템이 런북 기반 감별 진단 가능
4. 결과: LLM이 "CrashLoopBackOff" 대신 "NetworkDelay/NetworkLoss" 진단 가능
**대상 fault types**: F11 (primary), F12 (primary), F4 (minor — 노드 상태 간접 개선 가능)
**예상 효과**: 
- F11 B: 0% → 60-80% (+60-80pp)
- F12 B: 0% → 60-80% (+60-80pp)
- 전체 B: 38% → 48-55% (+10-17pp)
**리스크**: 
- gRPC 메트릭이 kube-prometheus-stack에서 scrape되지 않을 수 있음 (ServiceMonitor 필요)
- tc netem이 kubelet 통신에도 지연 적용 → F4 부작용으로 노드 NotReady 발생 가능
**구현 범위**: 
- `src/rag/config.py` — F11/F12 FAULT_TYPES 추가
- `src/collector/prometheus.py` — 메트릭 4종 추가
- `src/processor/context_builder.py` — 메트릭 포맷팅
- `docs/runbooks/rca-f11-networkdelay.md`, `rca-f12-networkloss.md` — 신규 런북
- `experiments/v8/` — V7 복사 + config 변경

### 가설 b: 클러스터 오염 제거 (Clean Cluster Recovery) — **우선순위 2**

**변경 변수**: Recovery 로직 강화 — fault 타입 전환 시 full manifest re-apply + endpoint 검증
**근거**:
- 데이터 근거: F11/F12 전 20 trial에서 `shippingservice CrashLoopBackOff (restarts=28+)` + `frontend 0 endpoints` 오염 확인. F4 전 10 trial에서도 동일 오염. 총 30건의 오답에 오염이 기여.
- 문헌 근거: 실험 환경 격리 원칙 — 각 trial은 독립적이어야 하며, 이전 trial의 잔류 상태가 다음 trial에 영향을 미쳐서는 안 됨
**메커니즘**: 
1. fault 타입 전환 시 원본 manifest 재적용 + 전체 pod 재시작
2. endpoint가 모두 populated 될 때까지 대기 (12+ pods Running + all endpoints > 0)
3. 오염 신호 제거 → LLM이 실제 fault 신호에만 집중 가능
**대상 fault types**: F4, F11, F12 (오염 영향), 그 외 모든 fault (간접)
**예상 효과**: 
- F11/F12: 오염 제거만으로 CrashLoopBackOff 오진 방지, 하지만 네트워크 메트릭 없으면 여전히 0%
- F1-F10: 1-2 trial 개선 가능 (오염 영향 제거)
- **주의**: 이 가설 단독으로는 F11/F12 개선 불가 (메트릭 부재는 별개 문제)
**리스크**: 낮음 (인프라 수정이므로 실험 변수와 독립)
**구현 범위**: 
- `scripts/stabilize/recovery.py` — full_reset 강화
- `scripts/stabilize/health_verify.py` — SSH 수정
- **참고**: 이것은 실험 변수가 아닌 환경 전제조건으로 분류 가능

### 가설 c: F9 역추적 강화 (Step 3 Backtracking Refinement) — **우선순위 3**

**변경 변수**: SOP 프롬프트의 Step 3 역추적 로직에 Secret/ConfigMap 우선 검사 강화
**근거**: 
- 데이터 근거: F9 B가 V3(80%) → V7(40%)로 -40pp 퇴행. V7 Step 3 역추적이 도입되었으나 F9 복구 미흡. F9 t2 (잘못된 포트) / t4 (Secret 키 오류) / t5 (base64 손상)에서 여전히 오답.
- 문헌 근거: SynergyRCA의 "엔티티 관계 추적" — Secret/ConfigMap 참조 관계를 명시적으로 컨텍스트에 포함
**메커니즘**: Step 3에서 "CreateContainerConfigError" 이벤트를 최우선 검사 → Secret/ConfigMap 참조 오류 확인
**대상 fault types**: F9 (primary), F5 (secondary)
**예상 효과**: F9 B: 40% → 60-80% (+20-40pp)
**리스크**: V6의 Step 3 흡수 문제 재발 가능 → 프롬프트 변경은 단일 변수 위반 가능성
**구현 범위**: `experiments/v8/prompts.py` — Step 3 세부 분기 조정

## 8. 요약 및 권장 우선순위

| 순위 | 가설 | 대상 | 예상 B 개선 | 리스크 | 비고 |
|------|------|------|-----------|--------|------|
| **1** | **a: 네트워크 신호 보강** | F11/F12 | **+10-17pp** | 중 (메트릭 가용성) | 가설 b를 전제조건으로 포함 |
| 2 | b: 클러스터 오염 제거 | 전체 | +1-3pp | 낮음 | **가설 a의 전제조건** (별도 실험 불필요) |
| 3 | c: F9 역추적 강화 | F9 | +3-7pp | 중 (V6 재발) | V8 이후 별도 실험으로 |

### 권장 실행 순서
1. **V8**: 가설 a (네트워크 신호 보강) + 가설 b를 전제조건으로 포함
   - 가설 b는 실험 변수가 아닌 환경 수정으로 처리
   - 프롬프트/엔진 변경 없음 → 단일 변수 = "네트워크 신호 보강"
2. **V9** (후속): 가설 c (F9 역추적) 또는 F4 노드 진단 강화

### 참조 문헌
- [SynergyRCA: StateGraph + LLM for K8s RCA](https://arxiv.org/abs/2506.02490)
- [gRPC OpenTelemetry Metrics Guide](https://grpc.io/docs/guides/opentelemetry-metrics/)
- [Modern Kubernetes Monitoring: Metrics, Tools, and AIOps](https://developers.redhat.com/articles/2025/12/17/modern-kubernetes-monitoring-metrics-tools-and-aiops)
- [LLMRCA: Multilevel RCA Using Multimodal Observability](https://dl.acm.org/doi/10.1145/3806200)
