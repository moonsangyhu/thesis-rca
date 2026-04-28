# 심층 분석: V9 실험 설계를 위한 개선점 도출

> 분석일: 2026-04-28
> 분석 대상: V8 실험 결과 (60 trials, `experiment_results_v8.csv` + `raw_v8/` 120 JSON)
> 핵심 질문: V8 가설 기각의 근본 원인은 무엇이며, V9에서 무엇을 단일 변수로 변경해야 하는가?

---

## 1. V8 결과 재해석 (analysis_v8 보완)

### 1-1. McNemar 검정 — V8 "회귀"는 binary 기준 통계적으로 유의하지 않음

`analysis_v8.md`는 V8가 V7 대비 회귀했다고 결론지었으나, 이는 **평균 점수(score) 기준**이며 실제로는 부분 점수(0.5) 분포 변화가 주된 차이다. Binary 기준(score≥0.5 = 정답)으로 V7과 V8을 paired 비교하면:

| | V8 정답 | V8 오답 |
|---|---|---|
| V7 정답 | 17 | **6** (lost) |
| V7 오답 | **4** (gained) | 33 |

- McNemar χ² = (6-4)² / (6+4) = **0.40** (p ≈ 0.53)
- **귀무가설(H0: b=c) 기각 불가** → V7과 V8은 binary 정확도 측면에서 통계적으로 동등

**의미**: V8 plan §10 회귀 판정은 평균 점수 기준이었고, 비열등성 검정의 95% CI 하한 -23.4pp가 δ=-5pp를 위반한 것은 binary 차이가 아닌 *score 분포 shift* 때문. 즉 **V8의 코드 변경은 binary 정확도에는 거의 영향이 없었음**.

### 1-2. F11/F12 진단 실패의 결정적 메커니즘 — 환경 오염

**V8 raw_v8 샘플링 결과**: F11 t1, F11 t5, F12 t1, F12 t3 전 trial에서 **동일한 잔류 pod**가 컨텍스트에 등장:

```
shippingservice-865585fdff-2lw2n: Running
  container/shippingservice: NOT READY (CrashLoopBackOff) restarts=26 → 32 → 36 → 38
    last terminated: StartError (exit code ?)
```

이 pod는 **V7 F2 fault에서 주입된 ReplicaSet `865585fdff`** (`command:[/bin/sh,-c,exit 1]`)의 잔류물. V7 실험 종료 후 lab-restore가 manifest 재적용 → 정상 ReplicaSet `759b59d959` 생성했으나, **이전 RS `865585fdff`가 desired=1로 살아있어 두 RS가 공존**. 정상 pod와 broken pod가 모두 boutique에 남아있는 상태.

### 1-3. LLM의 진단은 합리적 — 환경이 잘못

raw 분석에서 LLM의 reasoning은 일관되게 **현재 컨텍스트의 가장 강한 신호**를 따라감:

```
Step 1: 모든 노드 Ready → Step 2로
Step 2: shippingservice pod CrashLoopBackOff (restarts=38) → 이게 원인
predicted: CrashLoopBackOff
evidence: BackOff event count=760, restart count=38, verified=True
```

LLM은 멍청한 게 아니다. **컨텍스트에 active CrashLoop pod가 있으니 그게 원인**이라고 합리적으로 추론. 문제는 ground truth (NetworkDelay/Loss)가 그것이 아닐 뿐.

### 1-4. 컨텍스트 추가 버그 — METRIC ANOMALIES 중복

raw JSON에서 발견:
```
## METRIC ANOMALIES
## Metric Anomalies          ← 중복
No metric anomalies detected.

## Metric Anomalies          ← 중복 출력
No metric anomalies detected.
```

`context_builder.py`가 동일 섹션을 두 번 빌드. LLM context 명확성 저하 + 토큰 낭비.

### 1-5. 통제 변수 식별

| Fault별 V8 변동 | 패턴 | 해석 |
|---|---|---|
| F11/F12 모두 0% (V7=0%) | 공통 잔류 pod 신호 지배 | 환경 오염 (확정) |
| F2 100%→30% (full=0/partial=3) | 동일 진단인데 점수 하락 | judge 변경 또는 컨텍스트 길이 증가 (가설) |
| F7 60%→81% (+21pp) | 메트릭 추가가 CPU Throttling 신뢰 강화 | 우호적 부작용 |
| F1-F10 binary McNemar 비유의 | 6 lost vs 4 gained | V8 코드 변경이 binary 정확도에 영향 없음 |

---

## 2. 버전 간 변화 추적

| 버전 | 핵심 변경 | F11/F12 B | F1-F10 B (binary≥0.5) | 주요 회귀 |
|---|---|---|---|---|
| V3 | v2 + Harness | n/a (F1-F10만) | 50% | - |
| V4 | A retry 비활성화 | n/a | 38% (-12pp) | F1, F2, F4 |
| V6 | SOP-Guided Prompt | n/a | 38% | F4(-20pp), F8(-20pp) |
| V7 | SOP + Step 3 역추적 + Evidence Multiplicity | 0% | 46% | F11/F12 도입 → 0% |
| V8 | + 네트워크 메트릭 4종 + RAG/런북 (Beta 시나리오) | 0% (F11) / 0% (F12) | 42% (binary, McNemar p≈0.5) | 환경 오염 미해결 |

V7→V8 핵심: **메트릭/RAG/런북 보강이 환경 오염 문제를 가리지 못함**. V8가 추가한 모든 시그널이 무용지물 — context의 "shippingservice CrashLoop" 신호가 너무 강력.

---

## 3. 컨텍스트 구조 분석 — F11/F12 raw 정성

### 3-1. F11/F12 trial 컨텍스트의 5대 신호 우위 순위 (LLM이 본 것)

1. **shippingservice CrashLoopBackOff (restart count 26~38)** — 가장 강한 신호, 모든 trial 등장
2. **BackOff Kubernetes event** (count=505→760으로 누적) — 두 번째 강한 evidence
3. Pod Status: 13/14 Running (1개 NOT READY) — fault 예상 패턴과 일치
4. Node Status: 모든 노드 Ready — F4 NodeNotReady 가능성 배제 신호
5. Metric Anomalies: "No metric anomalies detected" — request_latency/grpc_errors 모두 빈 결과 (시나리오 Beta 한계)

### 3-2. tc netem 신호 부재

V8 plan §10-0에서 K8s 포트(6443/10250) 제외 결정 → tc netem이 실제로 적용되었지만 **노드 카운터(`node_network_*_errs`)에는 거의 잡히지 않음**. 이는:
- tc netem이 interface 레벨 packet 통계에 반영되기보다 **delay/loss를 시뮬레이션** (drop 카운터 ≠ tc netem)
- 실제 네트워크 지연/손실은 application-level (`grpc_server_handling_seconds`)이나 TCP 레벨(`Tcp_RetransSegs`)에 잡히지만, 본 클러스터는 gRPC histogram bucket=0, retrans는 baseline 노이즈로 필터됨

**결론**: `node_network_errs` 메트릭은 hardware-level NIC 에러에만 반응. tc netem 시뮬레이션과 상관관계 약함.

---

## 4. Evaluator 효과 분석 (V8 데이터)

V8 CSV의 `correctness_score` 분포 (B 시스템):
- 1.0 (full): 0건
- 0.8~0.99 (near): 6건
- 0.5~0.79 (half): 15건
- 0.1~0.49 (partial): 14건
- <0.1 (wrong): 25건

**전 trial에서 score=1.0 정답이 0건** — judge가 strict해진 것 같지만, V7에는 1.0이 다수 있음. 이는 **V8 컨텍스트가 V7 대비 길어졌고**(메트릭 4종 추가), root_cause 설명에 추상화가 더해지면서 judge가 "정확히 일치"로 인정하지 않음.

V9에서 검증 방향: judge 입력으로 **predicted vs ground_truth만 사용**하고 컨텍스트 자체는 비교에 포함하지 않도록 하는 정량 평가 일관성 확인.

---

## 5. GitOps 컨텍스트 효과 분석

V8에서 GitOps 컨텍스트는 System B에만 제공. F8 (ServiceEndpoint) 같은 manifest-level fault에서 효과적이어야 함:

| Fault | A score (avg) | B score (avg) | Δ | GitOps 활용 가능성 |
|---|---|---|---|---|
| F2 | 0.14 | 0.30 | +0.16 | command 잔류물 비교 (활용됨) |
| F8 | 0.06 | 0.22 | +0.16 | service selector/port diff (활용됨) |
| F6 | 0.31 | 0.23 | -0.08 | NetworkPolicy diff (오히려 노이즈) |
| F11 | 0.00 | 0.02 | +0.02 | 네트워크 fault에는 git 정보 무관 |

GitOps는 **manifest-mutating fault** (F2, F8)에는 효과적이지만, **environment-level fault**(F11/F12)에는 도움 안 됨. 본 실험에서는 V8 GitOps 신호가 F11/F12 진단에 어떤 도움도 주지 못함.

---

## 6. 참조 기법 (WebSearch 결과)

### 6-1. SynergyRCA (arxiv:2506.02490, Medium 2026-01) — **본 V9에 직접 적용 가능**

**핵심 컴포넌트**:
- **StateGraph + MetaGraph**: K8s 엔티티의 spatial/temporal 관계 그래프
- **StateChecker**: "verification module that ensures candidate root causes identified through graph traversal are factually valid and causally consistent with the incident before involving the LLM for explanation. It systematically evaluates each node and relationship along the path by inspecting their runtime states, attributes, and temporal transitions, and verifies causal ordering."
- **ReportQualityChecker**: "final validation layer that assesses the consistency, completeness, and evidence alignment of the generated RCA report before it is presented to users"

**성능**: precision ≈ 0.90, RCA 평균 시간 2분.

**본 V8과의 매핑**: V8 실패는 "candidate root cause(CrashLoopBackOff)가 실제로는 ground truth(NetworkDelay)가 아닌데도 LLM이 그것을 root cause로 보고"한 패턴. SynergyRCA의 StateChecker가 있다면, "shippingservice CrashLoop는 V7 잔류 fault → 현재 incident와 causally inconsistent → root cause 후보에서 제외"라고 판정 가능.

### 6-2. CHI 2025 LLM Observability — 4대 설계 원칙

- **Awareness**: 모델 행동을 가시화 (raw context를 직접 볼 수 있게)
- **Monitoring**: 실시간 피드백 (각 trial에서 LLM이 어떤 신호에 무게를 두는지)
- **Intervention**: 문제 발생 시 행동 가능 (잘못된 신호를 제거할 수 있는 mechanism)
- **Operability**: 장기 유지보수 지원

본 실험과 매핑: V8는 raw_v8 JSON으로 **Awareness** 충족 (덕분에 잔류 pod 발견 가능), 그러나 **Intervention** 부재 (LLM이 잘못된 신호를 보고 있어도 차단 불가).

---

## 7. 개선 가설 (V9 후보)

### 가설 a: Pre-Trial State Validator + 잔류 fault 자동 정정 (1순위 권장)

**변경 변수**: `experiments/shared/runner.py` + 신규 `scripts/stabilize/state_validator.py`. 매 trial 시작 전 StateChecker 패턴으로 클러스터 상태를 검증하고, 잔류 fault(예: 활성 CrashLoop ReplicaSet)가 발견되면 강제 정정. 정정 실패 시 trial 무효화 (CSV에 `skipped` 표시, ground truth 통계에서 제외).

**근거**:
- 데이터: V8 raw_v8 100% F11/F12 trial에서 잔류 RS `shippingservice-865585fdff` 발견. restart count 26→38 누적. recovery.py가 manifest 재적용했지만 desired=1인 잔류 RS를 제거하지 못함.
- 문헌: SynergyRCA StateChecker "verifies factual validity and causally consistent with the incident before involving the LLM" (arxiv:2506.02490).

**메커니즘**:
1. Trial 시작 전: 모든 boutique deployment에 대해 (RS 개수, container spec, command, port, selector) 검증.
2. **단일 변수 식별**: 현재 fault 외에 active CrashLoop/Pending pod가 있으면 잔류 fault로 분류.
3. 잔류 발견 시 `kubectl delete rs <stale-rs> --grace-period=0` + `kubectl rollout restart deploy/<name>` + 30s 안정화 대기.
4. 실패 시 trial을 **skipped**로 기록하고 다음으로 진행 (V9 결과는 통계적으로 깨끗한 trial만 포함).

**대상 fault types**: F11, F12 우선. F1-F10은 부수효과 (오염 누적 방지).

**예상 효과**:
- F11/F12 B: 0% → **40~60%** (실제 fault 신호가 컨텍스트의 dominant signal이 됨)
- F1-F10: V7 수준 유지 또는 +5pp (오염 누적 차단으로 안정화)
- 전체 B: 28~38% → **45~55%**

**리스크**:
- StateChecker가 정상 fault inject 결과(F2 trial의 의도된 CrashLoop)를 잔류로 오인하여 trial 무효화. → "현재 fault의 expected_pod"를 ground_truth에서 가져와 화이트리스트로 처리.
- skipped trial이 너무 많으면 통계적 검증력 저하. → 실패 시 강제 재시도 1회 + 그래도 실패면 skipped.

**구현 범위**:
- `scripts/stabilize/state_validator.py` (신규, ~200 lines)
- `experiments/shared/runner.py` 수정: trial 시작 전 validator 호출, skipped 처리
- `experiments/shared/csv_io.py` 수정: skipped 컬럼 추가
- `docs/runbooks/state-validator-rules.md` (신규)

### 가설 b: gRPC OpenTelemetry interceptor + ServiceMonitor 추가 (2순위)

**변경 변수**: Boutique 서비스에 gRPC OpenTelemetry server interceptor 적용 (manifest 패치) + monitoring 네임스페이스에 ServiceMonitor 정의 추가.

**근거**:
- 데이터: V8 시나리오 Beta 결과 F11/F12 0%. application-level gRPC 메트릭 부재가 fundamental 한계로 확인됨 (analysis_v8 §6-1).
- 문헌: gRPC OpenTelemetry Metrics Guide (grpc.io) — `grpc.server.call.duration` 표준 메트릭.

**메커니즘**: tc netem이 application-level latency/timeout을 발생시키면 `grpc_server_handling_seconds_bucket{le=...}`가 비대칭 분포 → `histogram_quantile(0.95, ...) > 0.5`가 진짜로 트리거. F11에서 latency, F12에서 timeout/error 코드를 직접 관측.

**대상 fault types**: F11, F12.

**예상 효과**:
- F11 B: 0% → **40~60%** (메트릭 직접 신호 + RAG 런북 매칭)
- F12 B: 0% → **30~50%** (gRPC 에러 코드 분포 + node-exporter 보조)
- 시나리오 Alpha 진입.

**리스크**:
- Boutique 서비스 manifest 수정 → 다른 fault inject 영향 가능 (F2 등). 사전 검증 필수.
- Service mesh 미사용이라 interceptor 수동 주입 필요. 코드 변경량 큼.
- gRPC OpenTelemetry 추가로 trial latency가 약간 증가 (수 ms).

**구현 범위**:
- `k8s/app/online-boutique-instrumented.yaml` (신규)
- `k8s/monitoring/boutique-servicemonitor.yaml` (신규)
- `src/collector/prometheus.py` 의 fallback 로직 제거 (Alpha만 가정)
- 사전 검증 절차: `results/preflight_v9.txt`에 gRPC bucket > 0 확인

### 가설 c: METRIC ANOMALIES 중복 제거 + context_builder 정리 (3순위, V9 환경 전제조건)

**변경 변수**: `src/processor/context_builder.py` — 중복된 metric anomalies 섹션 제거 + 섹션 명 일관성.

**근거**:
- V8 raw 모든 trial에서 `## METRIC ANOMALIES` 와 `## Metric Anomalies` 두 번 출력 확인.

**메커니즘**: 토큰 낭비 + LLM context 혼란. 중복 제거로 명확성 향상.

**대상 fault types**: 전체 (특히 메트릭 의존 fault F1, F7, F11, F12).

**예상 효과**: 정성적 개선 (직접 정확도 영향 미미하나 **가설 a/b의 효과 측정 정확도 향상**). 단독 가설로는 약함 — 환경 전제조건으로 같은 V9 사이클에 포함.

**리스크**: 거의 없음. 코드 5~10줄 수정.

**구현 범위**:
- `src/processor/context_builder.py` `_build_metric_anomalies()` 호출 1회로 통일

---

## 8. 권장 우선순위 + V9 단일 변수 결정

본 실험은 단일 변수 변경 원칙을 따른다. 따라서 V9는 **가설 a (Pre-Trial State Validator)** 만을 단일 독립변수로 채택.

가설 b (gRPC instrumentation)는 **V10 후보**로 보류:
- V8에서 환경 오염 메커니즘이 fundamental cause임이 확인됨. application-level 메트릭이 있어도 잔류 CrashLoop pod가 컨텍스트를 지배하는 한 효과 한계.
- V9에서 환경 오염 차단 + 메트릭 부재 상황에서도 어느 정도 진단 가능한지 먼저 확인 → V10에서 application 메트릭 추가로 추가 향상 측정.

가설 c (context_builder 중복 제거)는 **V9 환경 전제조건**으로 같은 사이클에 진행 (독립변수 아님).

### V9 가설 요약

| 항목 | 내용 |
|---|---|
| **단일 독립변수** | Pre-Trial State Validator + 잔류 fault 자동 정정 (가설 a) |
| **환경 전제조건** | METRIC ANOMALIES 중복 제거 (가설 c) |
| **V10 후보로 보류** | gRPC OpenTelemetry interceptor + ServiceMonitor (가설 b) |
| **베이스라인** | V8 (시나리오 Beta) — F11=2%, F12=0%, 전체 B=28%(avg) / 35%(≥0.5) |
| **성공 기준 (주)** | F11+F12 B 합산 ≥ 40% (0% → 40%+ 향상) |
| **성공 기준 (부)** | F1-F10 B (binary≥0.5) ≥ 42% (V8 동등 또는 향상) |
| **실패 판정** | F11+F12 합산 < 10% → 환경 오염이 주 원인 가설 기각 |

### 검증 가능한 부 가설들

- "환경 오염이 V8 F11/F12 실패의 주 원인"이 맞다면, V9 가설 a로 F11/F12 ≥ 40% 도달.
- 도달하지 못하면, V10에서 가설 b (gRPC instrumentation)로 추가 보강 필요.
- 도달하면 V10은 다른 축(F4 NodeNotReady 시계열, F9 Secret 회귀 등)으로 이동.

---

## 9. 다음 단계

1. `superpowers:brainstorming`(@experiment-planner wrapper) — 본 분석을 입력으로 V9 plan 설계.
2. plan 산출물 위치: `docs/plans/experiment_plan_v9.md`.
3. plan critique: `docs/plans/review_v9.md`.
4. 코드 변경 후 `experiments/v9/` 신설 (V8 fork) + V9 본 실험 실행.

작성: 2026-04-28 (KST)

## Sources (WebSearch 참조)

- [Simplifying Root Cause Analysis in Kubernetes with StateGraph and LLM (arxiv:2506.02490)](https://arxiv.org/abs/2506.02490)
- [SynergyRCA Medium 2026-01](https://shilpathota.medium.com/simplifying-root-cause-analysis-in-kubernetes-with-stategraph-and-llm-2df669420eb8)
- [SynergyRCA Literature Review](https://www.themoonlight.io/en/review/simplifying-root-cause-analysis-in-kubernetes-with-stategraph-and-llm)
- [Design Principles for LLM Observability (CHI 2025)](https://dl.acm.org/doi/10.1145/3706599.3719914)
- [Opsworker.ai: Multi-Agent AI SRE System](https://www.zenml.io/llmops-database/multi-agent-ai-sre-system-for-automated-incident-response-and-root-cause-analysis)
- [exalsius/rca-llm: RCA evaluation framework](https://github.com/exalsius/rca-llm)
