# V8 실험 결과 분석 리포트

**실험 일시**: 2026-04-27 19:54 ~ 2026-04-28 04:26 KST (8h 32m)
**시나리오**: Beta (gRPC 메트릭 부재 모드, `results/preflight_v8.txt` 기록)
**모델**: gpt-4o-mini (고정)
**총 trials**: 60 pairs (12 fault × 5 trials × 2 systems = 120 records)
**실험 코드**: commit `d2f0c41` (gRPC 노이즈 임계값 보정 포함)

---

## 1. 핵심 결과 요약

### 1-1. 전체 정확도 (B 시스템, correctness_score 기준)

| 지표 | V7 B | V8 B | Δ | Plan §10 기준 | 판정 |
|---|---|---|---|---|---|
| 전체 (F1-F12) | 38% | **28.3%** (avg) / **35.0%** (≥0.5) | -10pp / -3pp | ≥42% (Beta) | ❌ 미달 |
| F1-F10 | 46% | **33.8%** (avg) / **42.0%** (≥0.5) | -12pp / -4pp | 비열등성 δ=-5pp | ❌ 회귀 |
| F11 NetworkDelay | 0% | **2%** (avg) / **0%** (≥0.5) | +2pp / 0pp | ≥30% (Beta) | ❌ |
| F12 NetworkLoss | 0% | **0%** | 0pp | ≥30% (Beta) | ❌ |

**비열등성 검정 (F1-F10, score≥0.5 cutoff, plan §12-4)**:
- 21/50 (V8) − 23/50 (V7) = **-4.0pp**
- 95% CI = [-23.4, +15.4]pp
- CI 하한 **-23.4pp < δ=-5pp** → **비열등성 미입증, 회귀 발생**

**Fisher's exact (F11+F12, plan §12-2)**:
- V7 0/10, V8 0/10 → 차이 없음, V8 독립변수 효과 없음

### 1-2. Plan §10 실패 판정 기준 동시 적중

| 실패 기준 | 발동 여부 |
|---|---|
| F11+F12 B 합산 0% (개선 없음) | ✅ 적중 (V8: 합산 1%) |
| F1-F10 B < 38% (V7 대비 8pp 이상 하락) | ✅ 적중 (V8 avg 33.8%, ≥0.5 기준 42%) |

**결론: V8 가설 기각**. "네트워크 신호 보강(시나리오 Beta)"으로 F11/F12 진단 가능성을 확보하지 못했고, F1-F10에서 회귀까지 발생했다.

---

## 2. Fault별 결과 (V8 B vs V7 B)

| Fault | V7 B | V8 B (avg) | Δ (avg) | V8 B (≥0.5) | 진단 패턴 |
|---|---|---|---|---|---|
| F1 OOMKilled | 20% | 30% | +10pp | 1/5 | OOM Kill (1) / Network Config (1) — 분산 |
| F2 CrashLoopBackOff | **100%** | **30%** | **-70pp** | 0/5 | CrashLoop(3, score=0.5) / CPU Throttle(1) / Misconfig(1) — **부분 점수만** |
| F3 ImagePullBackOff | 60% | 46% | -14pp | 4/5 | Image Pull Failure (4) — 일관 |
| F4 NodeNotReady | 0% | 2% | +2pp | 0/5 | Service Connectivity (2) — 구조적 한계 |
| F5 PVCPending | 40% | 19% | -21pp | 1/5 | PVC Provisioning (2) / 부분점수 |
| F6 NetworkPolicy | 40% | 23% | -17pp | 1/5 | Network Connectivity (3) / Network Delay (1) — **F11과 혼동** |
| F7 CPUThrottle | **60%** | **81%** | **+21pp** | 5/5 | CPU Throttling (4) — V8 유일한 향상 |
| F8 ServiceEndpoint | 40% | 22% | -18pp | 1/5 | Endpoint Misconfig (3, partial) |
| F9 SecretConfigMap | 40% | 38% | -2pp | 2/5 | Missing Secret (2) / ConfigMap (1) |
| F10 ResourceQuota | 60% | 47% | -13pp | 4/5 | ResourceQuota Exceeded (4) — 일관 |
| **F11 NetworkDelay** | 0% | 2% | +2pp | 0/5 | **CrashLoopBackOff (4) / Application Crash (1)** |
| **F12 NetworkLoss** | 0% | 0% | 0pp | 0/5 | **CrashLoopBackOff (5)** — 100% 오진 |

---

## 3. 회귀 메커니즘 분석

### 3-1. F11/F12 진단 실패 — V7과 동일한 "클러스터 오염 → CrashLoopBackOff 오진" 패턴

**증거**: F11 5건 중 4건, F12 5건 중 5건이 "CrashLoopBackOff"로 오진. 이는 V7 분석(`docs/surveys/deep_analysis_v8.md`)에서 식별한 패턴과 정확히 일치.

**원인**: V8가 "Signal Enrichment"(메트릭+RAG+런북)를 도입했지만, **시나리오 Beta로 인해 핵심 메트릭(request_latency, grpc_errors)이 빈 결과**. 결과적으로 LLM 컨텍스트는 다음만 보유:
- 새 메트릭 4종 중 2종(node_network_errors, tcp_retransmissions)만 동작
- RAG F11/F12 런북 (인덱싱 정상)
- 그러나 실제 메트릭 시그널이 부족하여 **이전 fault의 잔류물(shippingservice CrashLoopBackOff)** 같은 비핵심 신호가 LLM 판단을 지배

**환경 잔류 증거**: 실험 종료 시점에 클러스터에 `shippingservice CrashLoopBackOff (restarts=99+)` 잔류. recovery.py의 `_full_reset()`가 SSH config 오류로 인해 `Comprehensive health check FAILED`를 반복하면서도 다음 trial을 진행 → 누적 오염.

### 3-2. F2 폭락 (V7 100% → V8 30%) — 평가 임계값 + 컨텍스트 노이즈

**증거**: F2 5건 중 정확한 "CrashLoopBackOff" 진단은 3건이지만, 모두 **score=0.5 (full=0건)**. V7에서는 5/5 모두 score=1.0 정답이었음.

**원인 가설**:
1. **Correctness Judge 평가 변경 가능성**: V8에서 judge prompt가 변경되지 않았다면 동일 진단에 다른 점수를 줄 이유가 없으나, 컨텍스트가 길어지면서 root_cause 설명의 specificity가 떨어졌을 수 있음. 5건 raw 검토 필요.
2. **컨텍스트 노이즈**: 새 메트릭 4종이 dry-run baseline에서는 0/14였지만, 실제 fault inject 중에는 일부 출력. F2 trial에서 "gRPC errors: etcdserverpb.KV Canceled" 같은 etcd 노이즈가 임계값(>0.1) 통과해 나타났을 가능성.
3. **shippingservice 잔류**: F2 trial 시점에 이전 V7/V8 fault로 인한 shippingservice 추가 RS가 활동 → "CrashLoopBackOff"로 진단했지만 ground truth와 정확히 일치하지 않아 부분점수.

다른 2건(CPU Throttling, Container Misconfiguration)은 명백한 오진. 이전 fault의 잔류물이 우세 신호로 작용했을 가능성.

### 3-3. F1-F10 광범위 회귀 — 새 메트릭의 활성 fault 중 노이즈

**dry-run vs 실제 fault 차이**: dry-run에서는 5건 모두 metrics 0/14였지만, 본 실험에서 실제 fault가 주입되면 다음 메트릭들이 진단을 흐릴 수 있음:
- **node_network_errors**: F4 NodeNotReady(2건 발생) 시 노드 NIC 에러 출력 → F11/F12와 혼동
- **tcp_retransmissions**: F2 CrashLoop 시 서비스 재시작으로 TCP 재전송 발생 → 네트워크 fault로 오인
- **grpc_errors (etcd fallback)**: 모든 fault에서 etcd 임계값(>0.1/s) 우연히 초과 가능

**증거**: F6 NetworkPolicy 5건 중 1건이 "Network Delay or Timeout"로 진단 — F11과 혼동. 새 네트워크 메트릭이 F6과 F11 사이의 감별을 어렵게 만들었음.

### 3-4. F7 단독 향상 (+21pp) — 의외의 결과

**가설**: V8에서 새 메트릭 중 `request_latency` 임계값이 dry-run에서 F7을 trigger하지 않도록 검증되었으나, 실제 fault에서는 **CPU 제한으로 인한 application 지연이 결과적으로 LLM이 CPU Throttling을 더 신뢰하게 만든 것**으로 추정. F7는 V7에서도 RAG 런북 매칭이 잘 작동하던 fault였으며, V8에서 대조군 안정화(V7과 동일 컨텍스트 + 약간의 메트릭 추가)로 +21pp 향상한 것으로 보임.

추가 검증을 위해 F7 raw context 비교 필요 (V7 vs V8 컨텍스트 길이/내용 diff).

---

## 4. 시나리오 Beta 적용성 평가

V8 plan §7-1에서 시나리오 Beta는 "node-exporter 메트릭 + RAG/런북으로 F11/F12 진단" 가능성을 가정. 결과적으로:

- **Beta 결과**: F11=0/5, F12=0/5 (≥0.5 cutoff) → 가설 기각
- **node-exporter 메트릭 한계 확인**: `node_network_errors`, `tcp_retransmissions`는 *interface 레벨* 신호로, *application 레벨* fault(서비스 간 지연)와 직접 매핑되지 않음. tc netem이 K8s 포트 제외 + interface 레벨 적용이라 노드 카운터에는 거의 잡히지 않을 가능성.
- **결론**: 시나리오 Beta는 fundamentally 부족. Online Boutique에 gRPC OpenTelemetry interceptor 또는 ServiceMonitor 추가가 필수 선결조건.

---

## 5. Plan §13 시나리오별 사후 분석

| 시나리오 | 플랜 정의 | V8 실제 결과 | 진단 |
|---|---|---|---|
| A: gRPC 메트릭 전혀 없음 | node-exporter + 로그 패턴 fallback | F11/F12 0% — fallback 효과 없음 | **시나리오 A 적중** |
| B: F11/F12 개선 없음 (0% 유지) | LLM이 메트릭 무시 or 수집 실패 → V9에서 프롬프트 강화 | "메트릭 수집 자체가 무의미"로 확인 | V9 ServiceMonitor 추가 우선 |
| C: F1-F10 회귀 발생 | 새 메트릭 노이즈 → threshold 조정 또는 조건부 출력 | F1-F10 -4pp ~ -12pp 회귀 | V9 조건부 출력 검토 |

---

## 6. V9 가설 후보 (우선순위)

### 6-1. (1순위) gRPC OpenTelemetry interceptor 추가 + ServiceMonitor 정의

**근거**: 시나리오 Beta가 fundamentally 부족함이 V8에서 입증. Boutique 서비스가 gRPC interceptor를 expose하지 않으면 어떤 fault enrichment 시도도 효과 한계.

**작업**:
- `src/instrumentation/` 신설하여 gRPC OpenTelemetry middleware injection
- monitoring 네임스페이스에 `ServiceMonitor` 추가하여 boutique 서비스 scrape
- 사전 점검에서 `grpc_server_handling_seconds_bucket > 0` 검증 통과 후에만 본 실험 진행

### 6-2. (2순위) Recovery 로직 SSH config 우회 + 강제 manifest 재적용

**근거**: V8에서 recovery.py의 health_verify가 SSH config 오류로 모든 disk check 실패 → 클러스터 오염 누적 → F11/F12 trial에서 shippingservice CrashLoopBackOff 잔류 신호로 인한 오진.

**작업**:
- `scripts/stabilize/recovery.py`의 SSH 명령에 `-F /dev/null` 옵션 추가 (사용자 SSH config 우회)
- `_full_reset()`에 manifest 절대 경로 사용 (현재는 `/tmp/thesis-rca-work/...` 가상 경로 의존)
- trial 간 fault 잔류 검증 강화 (shippingservice/cartservice/frontend 같은 핵심 서비스의 endpoint·command·port 일관성 체크)

### 6-3. (3순위) 새 메트릭 조건부 출력 (per-fault category)

**근거**: F6 NetworkPolicy가 F11과 혼동되는 패턴 확인. 새 메트릭이 모든 fault context에 출력되어 노이즈 작용.

**작업**:
- `src/processor/context_builder.py`에서 fault hint를 사용하지 않고 자동 분류 (예: pod_status에 CrashLoop 있으면 네트워크 메트릭 출력 억제)
- 또는 *시그널 우선순위* 시스템 도입 (CrashLoop > 네트워크 latency > etcd 노이즈)

### 6-4. (참고) F2 부분점수 문제 재현 검증

V8에서 F2 정답이 모두 0.5 score로 평가됨. judge prompt에 변경이 없다면 root_cause 설명의 specificity 차이일 수 있음. F2 raw_v8 5건과 raw_v7 5건의 root_cause 텍스트 diff를 통해 평가 일관성 확인 필요.

---

## 7. 산출물 인덱스

| 항목 | 경로 |
|---|---|
| 사전 점검 + 시나리오 결정 | `results/preflight_v8.txt` |
| Dry-run 5건 | `results/dryrun_v8/{F1,F2,F7,F11,F12}_t1.txt` |
| Dry-run 종합 | `results/dryrun_v8/SUMMARY.md` |
| 실험 결과 CSV | `results/experiment_results_v8.csv` (120 records) |
| Trial별 raw context | `results/raw_v8/F{N}_t{X}_{A,B}_*.json` (120 files) |
| 실행 로그 | `results/experiment_v8.log`, `results/experiment_v8_nohup.log` |
| 본 분석 리포트 | `results/analysis_v8.md` |
| 계획서 | `docs/plans/experiment_plan_v8.md` (1차 리비전 2026-04-27) |
| 리뷰 | `docs/plans/review_v8.md` (필수 5건 모두 반영) |

---

## 8. 다음 단계 권고

1. **즉시**: 본 리포트 + raw_v8 데이터로 V9 deep_analysis 작성 (`/deep-analysis`).
2. **V9 가설**: 위 §6-1 (gRPC interceptor + ServiceMonitor)을 우선 검증 가설로 채택. §6-2 (recovery 로직)도 환경 전제조건으로 같은 V9 사이클에 포함.
3. **메소드 개선**: V9 plan에 *trial 간 클러스터 오염 검증 게이트* 추가 (현재는 health_check이 통과/실패만 보고하고 다음 trial을 진행). 오염 감지 시 즉시 강제 재초기화 + 해당 trial 결과 무효화 옵션.
4. **본 V8 데이터 보존**: 실패 결과도 V9 baseline으로 가치 있음. 논문에서 "Signal Enrichment without proper instrumentation = ineffective" 근거로 활용 가능.

작성: 2026-04-28 (KST)
