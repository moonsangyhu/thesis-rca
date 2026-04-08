# V7 실험 계획서: Step 3 역추적 + 증거 다중성 + F11/F12 네트워크 Fault

> 작성일: 2026-04-08
> 작성자: experiment-planner agent
> 베이스라인: V6 (SOP-Guided Diagnosis)
> 독립변수: SYSTEM_PROMPT Step 3 역추적 로직 + 증거 다중성 규칙 (프롬프트 단일 변수)
> 추가: F11/F12 네트워크 fault 신규 도입 + comprehensive_health_check 강화

---

## 1. 실험 목적

V6의 SOP Step 3 흡수 문제를 해결하여 F9/F6/F5의 정확도를 V3 수준 이상으로 복원하고, F7/F2/F8의 개선은 유지한다. 동시에 F11/F12 네트워크 계층 fault를 추가하여 실험 범위를 확장하고, health check를 강화하여 실험 신뢰성을 높인다.

### 배경 및 동기

V6에서 SOP 프롬프트가 F7(+40pp), F2(+40pp), F8(+20pp)에서 큰 개선을 보였으나, Step 3의 "0 endpoints" 진단이 다른 fault의 근본 원인을 흡수하는 문제가 발생했다:

| Fault | V3_B | V6_B | 변화 | 원인 |
|-------|------|------|------|------|
| F9 SecretConfigMap | 80% | 20% | **-60pp** | 0 endpoints가 Secret 누락 원인을 흡수 |
| F6 NetworkPolicy | 40% | 0% | **-40pp** | 0 endpoints가 NetworkPolicy 차단 원인을 흡수 |
| F5 PVCPending | 60% | 20% | **-40pp** | 0 endpoints가 PVC Pending 원인을 흡수 |

핵심 문제: V6 Step 3은 "0 endpoints이면 Service selector/targetPort/readiness probe 확인"으로만 안내한다. 그러나 0 endpoints는 NetworkPolicy 차단, PVC Pending으로 인한 Pod 미생성, Secret 누락으로 인한 CreateContainerConfigError 등 다양한 상위 원인의 **증상**이다. Step 3에서 이를 원인으로 확진하면 실제 근본 원인을 놓치게 된다.

### V6 교훈

| 성공 패턴 | 실패 패턴 |
|-----------|-----------|
| SOP 직접 매칭이 효과적 (F7 CPU throttle, F2 CrashLoop) | Step 3 흡수: 0 endpoints가 F6/F5/F9의 근본 원인을 대체 |
| 조건부 진행이 V4 분류 잠금 없이 작동 | 단일 신호 의존: 하나의 눈에 띄는 증상만으로 확진 |
| Priority Rule이 다중 이상 시 올바르게 작동 | 역추적 부재: 증상→원인 역추적 로직이 없음 |

### 가설

V6의 SOP Step 3에 근본 원인 역추적 로직을 추가하고, 증거 다중성 규칙을 도입하면, Step 3 흡수 문제가 해결되어 F9/F6/F5의 정확도가 V3 수준 이상으로 복원되면서 F7/F2/F8의 개선은 유지된다.

**핵심 메커니즘**:
1. Step 3 역추적: "0 endpoints는 증상이다" → NetworkPolicy/PVC/Secret 등 상위 원인을 먼저 확인
2. 증거 다중성: 단일 신호만으로 확진 불가, 2개 이상 독립 소스 필요

---

## 2. 이전 결과 분석 요약

### 전체 정답률 (V3-V6)

| 버전 | System A | System B | B-A 격차 | 비고 |
|------|----------|----------|----------|------|
| V3 | 30% (15/50) | 40% (20/50) | +10pp | 현재 최고 |
| V4 | 20% (8/40) | 32.5% (13/40) | +12.5pp | 분류 잠금 |
| V5 | 23.5% (8/34) | 26.5% (9/34) | +3pp | 정보 손실 |
| V6 | 26% (13/50) | 38% (19/50) | +12pp | Step 3 흡수 |

### Fault type별 V3 vs V6 비교 (베이스라인)

| Fault | V3_A | V3_B | V6_A | V6_B | V6-V3 delta_B | 분석 |
|-------|------|------|------|------|---------------|------|
| F1 OOMKilled | 20% | 20% | 20% | 20% | 0pp | 변동 없음 |
| F2 CrashLoop | 20% | 20% | 20% | 60% | **+40pp** | SOP 직접 매칭 성공 |
| F3 ImagePull | 40% | 20% | 40% | 40% | +20pp | 개선 |
| F4 NodeNotReady | 0% | 0% | 0% | 0% | 0pp | 여전히 전체 실패 |
| F5 PVCPending | 40% | 60% | 20% | 20% | **-40pp** | Step 3 흡수 |
| F6 NetworkPolicy | 0% | 40% | 0% | 0% | **-40pp** | Step 3 흡수 |
| F7 DiskPressure | 60% | 60% | 40% | 100% | **+40pp** | SOP 직접 매칭 성공 |
| F8 ServiceEndpoint | 20% | 40% | 20% | 60% | +20pp | SOP Step 3 매칭 |
| F9 SecretConfigMap | 60% | 80% | 40% | 20% | **-60pp** | Step 3 흡수 (최악) |
| F10 ResourceQuota | 40% | 60% | 60% | 60% | 0pp | 유지 |

### 핵심 실패 원인 Top 3

1. **Step 3 흡수 (Absorption by Step 3)**: "0 endpoints"라는 단일 증상이 F6(NetworkPolicy), F5(PVC Pending), F9(Secret/ConfigMap)의 근본 원인을 대체. Step 3에서 "0 endpoints → Service endpoint 문제"로 조기 확진하여 실제 원인을 탐색하지 않음.

2. **단일 신호 의존 (Single Signal Dependency)**: LLM이 가장 눈에 띄는 하나의 신호만으로 진단을 확정. 2차 확인 없이 바로 결론으로 점프. 특히 0 endpoints, CrashLoopBackOff 같은 강한 신호가 있으면 다른 가능성을 무시.

3. **F4 NodeNotReady 지속 실패**: V3~V6 전 버전에서 0%. 노드 수준 장애의 시그널 수집이 근본적으로 부족하거나, kubelet 중단 시 메트릭 자체가 사라지는 문제 가능성.

### System B 우위/열위 패턴 (V6)

**B > A (SOP + GitOps 시너지)**:
- F7: B=100%, A=40% (+60pp) — CPU throttle 메트릭 + SOP Step 5 직접 매칭
- F2: B=60%, A=20% (+40pp) — CrashLoopBackOff + SOP Step 2 직접 매칭
- F8: B=60%, A=20% (+40pp) — 0 endpoints + SOP Step 3 매칭 (이 경우 정답)

**B < A (GitOps/RAG 노이즈 또는 흡수)**:
- F9: B=20%, A=40% (-20pp) — GitOps 컨텍스트가 Step 3 흡수를 강화
- F7 제외하고 B=A인 fault가 많음 — SOP가 GitOps 컨텍스트를 충분히 활용하지 못함

---

## 3. 개선 사항 상세: 3개 워크스트림

### W1: 프롬프트 수정 (독립변수, V6 대비 단일 변수)

#### 수정 A — Step 3 역추적 로직

**변경 전 (V6 Step 3)**:
```
Step 3 - Check Service Connectivity: Are any services showing 0 endpoints or endpoint mismatches?
  → If YES: Check Service selector vs pod labels, targetPort vs containerPort,
  readiness probe configuration.
  → If NO: Proceed to Step 4.
```

**변경 후 (V7 Step 3)**:
```
Step 3 - Check Service Connectivity: Are any services showing 0 endpoints or endpoint mismatches?
  → If YES: CRITICAL — 0 endpoints is a SYMPTOM, not a root cause. You MUST trace back to the
  underlying reason before diagnosing:
    (a) Check NetworkPolicy/CiliumNetworkPolicy: Are there policy drops (cilium_drop_count_total)?
        Is there a deny-all or blocking policy? → If YES: Root cause is NetworkPolicy, not Service.
    (b) Check PVC/Storage: Are any PVCs in Pending state? Is a StorageClass missing or
        provisioner unavailable? → If YES: Root cause is PVC/Storage preventing Pod scheduling.
    (c) Check Secret/ConfigMap: Are any pods in CreateContainerConfigError? Are referenced
        Secrets/ConfigMaps missing? → If YES: Root cause is missing Secret/ConfigMap.
    (d) Check Pod scheduling: Are pods Pending due to ResourceQuota, node affinity, or taints?
        → If YES: Root cause is scheduling constraint.
    → ONLY if (a)-(d) are ALL negative: Diagnose as Service Endpoint misconfiguration
      (selector mismatch, wrong targetPort, etc.)
  → If NO: Proceed to Step 4.
```

**근거**: V6에서 F9(-60pp), F6(-40pp), F5(-40pp) 하락의 직접적 원인이 Step 3의 조기 확진. 역추적 로직은 "0 endpoints"를 증상으로 재정의하고, 상위 원인을 체계적으로 확인하도록 강제한다. F8(실제 Service endpoint 문제)은 (a)-(d)가 모두 음성이므로 기존 진단 경로를 유지한다.

**예상 효과**:
- F9 복원: 20% → 60%+ (CreateContainerConfigError 역추적으로 Secret 누락 식별)
- F6 복원: 0% → 40%+ (cilium drops 역추적으로 NetworkPolicy 식별)
- F5 복원: 20% → 40%+ (PVC Pending 역추적으로 스토리지 문제 식별)
- F8 유지: 60% 유지 (역추적 (a)-(d) 모두 음성이므로 기존 경로)

#### 수정 B — 증거 다중성 규칙

**추가 위치**: Priority Rule 바로 뒤

**추가 내용**:
```
## Evidence Multiplicity Rule (CRITICAL)
Before confirming ANY diagnosis, you MUST have at least 2 independent supporting signals
from DIFFERENT sources (e.g., metric + log, event + metric, gitops_diff + event).
A single signal alone is NEVER sufficient for a confirmed diagnosis.

Independent sources are:
- Prometheus metrics (container_*, kube_*, node_*)
- Application/system logs (Loki)
- Kubernetes events (kubectl get events)
- GitOps diffs (Flux/Argo state changes)
- Pod/Node status (kubectl describe)

If only 1 signal supports your diagnosis:
- Set confidence < 0.7
- Explicitly state "single signal only" in reasoning
- Actively search for corroborating evidence in the remaining context
```

**근거**: V6 실패 분석에서 단일 신호 의존이 반복. "0 endpoints"라는 하나의 신호만으로 확진하는 패턴이 흡수 문제의 근본 원인. 다중성 규칙은 2차 확인을 강제하여 조기 확진을 방지한다.

**예상 효과**:
- 단일 신호 기반 오진단 감소
- confidence가 더 정확하게 보정됨
- F7(CPU throttle)은 메트릭 + 이벤트 + Pod 상태 등 다수 신호가 존재하므로 안전

**리스크**: 기존 잘 맞추던 fault(F7, F10)에서 다중 신호를 찾지 못해 confidence를 낮추거나 진단을 변경할 위험. 그러나 F7의 CPU throttle은 `container_cpu_cfs_throttled_periods_total`(메트릭) + 높은 latency(로그) + Pod running but slow(상태) 등 3개 이상 독립 신호가 존재하므로 안전하다.

### W2: F11/F12 네트워크 Fault 추가

Flow-of-Action 논문(ACM WWW 2025)에서 사용하지만 현재 실험에 없는 네트워크 계층 fault를 추가하여 실험 범위를 확장한다.

#### F11 — Network Delay (tc netem delay)

네트워크 지연을 주입하여 서비스 간 통신 타임아웃 및 latency 급증을 유발한다.

| Trial | 타겟 노드 | 설정 | 시나리오 |
|-------|-----------|------|----------|
| t1 | worker01 | 500ms delay | 경미한 지연, 타임아웃 경계 |
| t2 | worker02 | 1s delay, 200ms jitter | 중간 지연 + 불안정 |
| t3 | worker01 | 2s delay | 심각한 지연, gRPC deadline 초과 |
| t4 | worker03 | 300ms delay, normal distribution | 경미하지만 분포 있는 지연 |
| t5 | worker02 | 5s delay | 근접 타임아웃, 거의 연결 불가 |

**주입 명령**:
```bash
# SSH로 워커 노드에 접속하여 실행
ssh worker0X "sudo tc qdisc add dev IFACE root netem delay {delay}ms {jitter}ms"
```

**복구 명령**:
```bash
ssh worker0X "sudo tc qdisc del dev IFACE root"
```

**ground_truth.csv 추가 항목**:
- fault_name: NetworkDelay
- expected_root_cause: Network delay of {N}ms injected on {node}, causing gRPC deadline exceeded and increased latency
- primary_symptoms: High p99 latency, gRPC DEADLINE_EXCEEDED, connection timeouts
- expected_metrics: `histogram_quantile(0.99, rate(grpc_server_handling_seconds_bucket[5m]))` spike
- expected_log_patterns: deadline exceeded, context deadline exceeded, timeout

#### F12 — Network Loss (tc netem loss)

네트워크 패킷 손실을 주입하여 서비스 간 통신 실패 및 재전송을 유발한다.

| Trial | 타겟 노드 | 설정 | 시나리오 |
|-------|-----------|------|----------|
| t1 | worker01 | 10% loss | 경미한 손실, 간헐적 실패 |
| t2 | worker02 | 30% loss | 중간 손실, 빈번한 재전송 |
| t3 | worker03 | 50% loss | 심각한 손실, 서비스 불안정 |
| t4 | worker01 | 5% loss, 25% correlation | 버스트 손실 패턴 |
| t5 | worker02 | 80% loss | 극심한 손실, 거의 통신 불가 |

**주입 명령**:
```bash
ssh worker0X "sudo tc qdisc add dev IFACE root netem loss {loss}% {correlation}%"
```

**복구 명령**:
```bash
ssh worker0X "sudo tc qdisc del dev IFACE root"
```

**ground_truth.csv 추가 항목**:
- fault_name: NetworkLoss
- expected_root_cause: Network packet loss of {N}% on {node}, causing retransmissions and service failures
- primary_symptoms: Connection reset, retransmission spikes, intermittent failures
- expected_metrics: `node_network_transmit_errs_total` increase, TCP retransmission metrics
- expected_log_patterns: connection reset by peer, EOF, broken pipe

#### F11/F12 안전 조치

1. **SSH 포트 제외**: tc netem 규칙 적용 시 SSH 포트(22)를 제외하여 복구 명령 실행 보장
   ```bash
   # SSH 트래픽 보호 필터
   tc qdisc add dev IFACE root handle 1: prio
   tc qdisc add dev IFACE parent 1:3 netem delay {N}ms
   tc filter add dev IFACE protocol ip parent 1:0 prio 1 u32 match ip dport 22 0xffff flowid 1:1
   tc filter add dev IFACE protocol ip parent 1:0 prio 1 u32 match ip sport 22 0xffff flowid 1:1
   tc filter add dev IFACE protocol ip parent 1:0 prio 2 u32 match ip dst 0.0.0.0/0 flowid 1:3
   ```

2. **자동 만료**: 안전을 위해 `timeout` 명령으로 자동 해제
   ```bash
   ssh worker0X "sudo timeout 600 tc qdisc add dev IFACE root netem delay {N}ms || true"
   ```
   주의: `timeout`은 `tc` 자체가 즉시 종료되므로 다른 방식 필요. 대안으로 cronjob/at 사용:
   ```bash
   ssh worker0X "sudo tc qdisc add dev IFACE root netem delay {N}ms && echo 'sudo tc qdisc del dev IFACE root 2>/dev/null' | at now + 10 minutes"
   ```

3. **네트워크 인터페이스 식별**: 각 워커 노드의 primary 인터페이스를 사전에 확인
   ```bash
   ssh worker0X "ip route | grep default | awk '{print \$5}'"
   ```

#### SOP 프롬프트에 F11/F12 대응 추가

Step 3과 Step 4 사이에 네트워크 성능 체크를 삽입하는 것이 자연스러우나, V7의 독립변수를 최소화하기 위해 **기존 Step 4 Network 단계의 설명을 확장**한다:

```
Step 4 - Check Network: Are there cilium policy drops, connection refused errors, DNS
resolution failures, abnormally high latency (p99 > 1s), or packet loss indicators in
logs or metrics?
  → If connection timeout / deadline exceeded WITHOUT cilium drops: Check for network
    performance degradation (delay, packet loss, bandwidth). Look for latency spikes in
    histogram_quantile metrics and retransmission errors.
  → If cilium drops present: Check NetworkPolicy rules, CiliumNetworkPolicy, DNS service health.
  → If NO: Proceed to Step 5.
```

### W3: 100% 클러스터 복원 보장 — comprehensive_health_check()

V6에서 health_check()의 불충분함으로 인해 이전 fault 잔여물이 다음 trial에 영향을 미치는 가능성이 있었다. 7항목 종합 검증으로 강화한다.

#### 7항목 검증

```python
def comprehensive_health_check() -> bool:
    """7-point cluster health verification."""
    checks = {
        "nodes_ready": _check_nodes_ready,           # 1. 모든 노드 Ready + DiskPressure=False
        "deployments_ready": _check_deployments,      # 2. 12개 디플로이먼트 readyReplicas == replicas
        "pods_healthy": _check_pods_healthy,          # 3. Failed/Pending/CrashLoop 0개
        "residuals_clean": _check_residuals,          # 4. NetworkPolicy/ResourceQuota/LimitRange 잔여 0개
        "endpoints_populated": _check_endpoints,      # 5. 모든 서비스 subsets 비어있지 않음
        "disk_usage": _check_disk_usage,              # 6. 전 워커 디스크 < 80%
        "monitoring_healthy": _check_monitoring,      # 7. Prometheus + Loki 정상
    }

    results = {}
    for name, check_fn in checks.items():
        try:
            results[name] = check_fn()
        except Exception as e:
            logger.error("Health check '%s' failed with exception: %s", name, e)
            results[name] = False

    passed = all(results.values())
    if not passed:
        failed = [k for k, v in results.items() if not v]
        logger.warning("Health check FAILED: %s", failed)
    return passed
```

#### 실패 시 복구 전략

```python
def ensure_healthy(max_retries=3) -> bool:
    """Health check with retry and full_reset fallback."""
    for attempt in range(max_retries):
        if comprehensive_health_check():
            return True
        logger.warning("Health check attempt %d/%d failed, waiting 30s...", attempt+1, max_retries)
        time.sleep(30)

    # All retries failed — execute full_reset
    logger.error("All health check retries failed. Executing full_reset...")
    full_reset()

    # Final verification after reset
    time.sleep(60)
    if comprehensive_health_check():
        logger.info("Cluster recovered after full_reset")
        return True

    logger.error("CRITICAL: Cluster not recoverable after full_reset")
    return False
```

#### 각 검증 항목 상세

1. **노드 검증**: `kubectl get nodes -o json` → 모든 노드 `Ready=True`, `DiskPressure=False`, `MemoryPressure=False`
2. **디플로이먼트 검증**: `kubectl get deploy -n boutique -o json` → 12개 디플로이먼트 `readyReplicas == replicas`
3. **Pod 검증**: `kubectl get pods -n boutique -o json` → `Failed`, `Pending` phase 없음, `CrashLoopBackOff` waiting reason 없음
4. **잔여물 검증**: `kubectl get networkpolicy,resourcequota,limitrange -n boutique -o json` → 아이템 0개 (boutique 네임스페이스에 기본 정책 없음)
5. **엔드포인트 검증**: `kubectl get endpoints -n boutique -o json` → 모든 서비스의 `subsets[].addresses` 비어있지 않음
6. **디스크 검증**: `ssh worker0X "df -h /"` → 사용률 80% 미만
7. **모니터링 검증**: Prometheus API `/-/healthy`, Loki API `/ready` 응답 확인

---

## 4. 통제변수 (V6과 동일)

| 항목 | V6 값 | V7 값 | 비고 |
|------|-------|-------|------|
| LLM 모델 | gpt-4o-mini | gpt-4o-mini | 모델 고정 원칙 |
| MAX_TOKENS | 2048 | 2048 | 동일 |
| MAX_RETRIES | 2 | 2 | 동일 |
| LLM 호출 횟수 (Generator) | 1회 | 1회 | 동일 |
| Context Builder | V3 ContextBuilder | V3 ContextBuilder | 동일 |
| EVALUATOR_PROMPT | V3 그대로 | V3 그대로 | 동일 |
| RETRY_PROMPT_TEMPLATE | V3 그대로 | V3 그대로 | 동일 |
| Retry 정책 | B만 활성 | B만 활성 | 동일 |
| Evidence Verification | 실행 (상수 1.0) | 실행 (상수 1.0) | 동일 |
| RAG | KnowledgeRetriever | KnowledgeRetriever | 동일 |
| GitOps 컨텍스트 | V3 ContextBuilder 전체 포함 | 동일 | 동일 |
| Correctness Judge | CORRECTNESS_JUDGE_PROMPT | 동일 | 동일 |
| Signal Collection | V3 수집 쿼리 | 동일 (F1-F10), 확장 (F11/F12) | F11/F12만 추가 |
| JSON 출력 스키마 | V3 RCAOutput | 동일 | 동일 |

---

## 5. Fault별 SOP 매핑 및 예상 효과

### 기존 F1-F10: V7 Step 3 역추적 효과 예측

| Fault | V3_B | V6_B | V7 SOP 매핑 | V7 변경 영향 | V7_B 예상 |
|-------|------|------|-------------|-------------|-----------|
| F1 OOMKilled | 20% | 20% | Step 2 OOMKilled | 변동 없음 (Step 3 무관) | 20% |
| F2 CrashLoop | 20% | 60% | Step 2 CrashLoopBackOff | **유지** (Step 3 무관) | 60% |
| F3 ImagePull | 20% | 40% | Step 2 ImagePullBackOff | 변동 없음 (Step 3 무관) | 40% |
| F4 NodeNotReady | 0% | 0% | Step 1 Node Health | 변동 없음 (근본적 시그널 부족) | 0% |
| F5 PVCPending | 60% | 20% | **Step 3(b) PVC 역추적** | **복원** — PVC Pending 확인 | 40-60% |
| F6 NetworkPolicy | 40% | 0% | **Step 3(a) NetworkPolicy 역추적** | **복원** — cilium drops 확인 | 20-40% |
| F7 DiskPressure | 60% | 100% | Step 1 DiskPressure | **유지** (Step 3 무관) | 80-100% |
| F8 ServiceEndpoint | 40% | 60% | Step 3 fallthrough (a-d 음성) | **유지** — 역추적 후 Service 문제 확진 | 60% |
| F9 SecretConfigMap | 80% | 20% | **Step 3(c) Secret/ConfigMap 역추적** | **복원** — CreateContainerConfigError 확인 | 60-80% |
| F10 ResourceQuota | 60% | 60% | Step 2 Pending + Step 5 | 변동 없음 (Step 3 무관) | 60% |

### 신규 F11/F12: 베이스라인 수립

| Fault | 특성 | SOP 매핑 | 예상 난이도 |
|-------|------|----------|-----------|
| F11 NetworkDelay | latency spike, deadline exceeded | Step 4 확장 (high latency) | 중간 — latency 메트릭이 명확 |
| F12 NetworkLoss | retransmission, connection reset | Step 4 확장 (packet loss) | 높음 — 증상이 다양하게 나타남 |

---

## 6. 구현 범위

### 파일 구조

```
experiments/v7/
    __init__.py          # RCAEngineV7 export
    config.py            # V6 포크, 경로만 v7으로 변경, F11/F12 추가
    prompts.py           # V6 SOP + Step 3 역추적 + 증거 다중성 + Step 4 확장
    engine.py            # V6 포크, 클래스명 RCAEngineV7
    run.py               # V6 포크, F11/F12 포함, comprehensive_health_check 적용

scripts/fault_inject/
    injector.py          # F11/F12 주입 메서드 추가

scripts/stabilize/
    recovery.py          # F11/F12 복구 메서드 추가

experiments/shared/
    runner.py            # ALL_FAULTS에 F11/F12 추가
    infra.py             # comprehensive_health_check() 추가 또는 교체

results/
    ground_truth.csv     # F11/F12 × 5 trials = 10행 추가
```

### 코드 수정 체크리스트

- [ ] `experiments/v7/__init__.py` — `from .engine import RCAEngineV7` export
- [ ] `experiments/v7/config.py` — V6 config.py 복사, 경로를 `experiment_results_v7.csv`, `raw_v7/`로 변경
- [ ] `experiments/v7/prompts.py` — V7_SOP_SYSTEM_PROMPT 신규 작성 (Step 3 역추적 + 증거 다중성 + Step 4 확장)
- [ ] `experiments/v7/engine.py` — V6 engine.py 복사, 클래스명 `RCAEngineV7`, import 변경
- [ ] `experiments/v7/run.py` — V6 run.py 복사, comprehensive_health_check 적용, F11/F12 포함
- [ ] `scripts/fault_inject/injector.py` — `_inject_f11_network_delay()`, `_inject_f12_network_loss()` 추가
- [ ] `scripts/stabilize/recovery.py` — F11/F12 복구 로직 추가 (`tc qdisc del`)
- [ ] `experiments/shared/runner.py` — `ALL_FAULTS` 확장 (`F1-F12`)
- [ ] `experiments/shared/infra.py` — `comprehensive_health_check()` 추가
- [ ] `results/ground_truth.csv` — F11 t1-t5 + F12 t1-t5 = 10행 추가
- [ ] dry-run 테스트 통과 (F1 t1, F6 t1, F11 t1)

### prompts.py 핵심 변경 부분

V6 `SOP_GUIDED_SYSTEM_PROMPT`에서 다음 3곳만 변경:

**1) Step 3 교체** (약 4줄 → 12줄):
```python
# 변경 전 (V6)
"""Step 3 - Check Service Connectivity: Are any services showing 0 endpoints or endpoint mismatches?
  → If YES: Check Service selector vs pod labels, targetPort vs containerPort,
  readiness probe configuration.
  → If NO: Proceed to Step 4."""

# 변경 후 (V7)
"""Step 3 - Check Service Connectivity: Are any services showing 0 endpoints or endpoint mismatches?
  → If YES: CRITICAL — 0 endpoints is a SYMPTOM, not a root cause. You MUST trace back:
    (a) Check NetworkPolicy: cilium_drop_count_total increasing? deny-all policy?
        → YES: Root cause is NetworkPolicy block, not Service issue.
    (b) Check PVC/Storage: Any PVC Pending? StorageClass missing? Provisioner down?
        → YES: Root cause is PVC/Storage preventing Pod creation.
    (c) Check Secret/ConfigMap: Any pod in CreateContainerConfigError?
        → YES: Root cause is missing Secret/ConfigMap.
    (d) Check scheduling: Pods Pending due to ResourceQuota, affinity, taints?
        → YES: Root cause is scheduling constraint.
    → ONLY if (a)-(d) ALL negative: Service Endpoint misconfiguration (selector, targetPort).
  → If NO: Proceed to Step 4."""
```

**2) Step 4 확장** (1줄 추가):
```python
# 변경 전 (V6)
"""Step 4 - Check Network: Are there cilium policy drops, connection refused errors, or DNS
resolution failures in logs or metrics?"""

# 변경 후 (V7)
"""Step 4 - Check Network: Are there cilium policy drops, connection refused errors, DNS
resolution failures, abnormally high latency (p99 > 1s), or packet loss/retransmission
indicators in logs or metrics?
  → If timeout/deadline exceeded WITHOUT cilium drops: Network performance degradation
    (delay, loss). Check histogram_quantile latency and retransmission metrics."""
```

**3) 증거 다중성 규칙 추가** (Priority Rule 뒤):
```python
"""## Evidence Multiplicity Rule (CRITICAL)
Before confirming ANY diagnosis, you MUST have at least 2 independent supporting signals
from DIFFERENT sources (metric + log, event + metric, gitops_diff + event, etc.).
Single signal alone → confidence < 0.7, state "single signal only" in reasoning."""
```

### config.py 변경

```python
"""v7 experiment configuration: Step 3 Backtracking + Evidence Multiplicity."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
RESULTS_DIR = PROJECT_ROOT / "results"
RESULTS_CSV = RESULTS_DIR / "experiment_results_v7.csv"
RAW_DIR = RESULTS_DIR / "raw_v7"
GROUND_TRUTH_CSV = RESULTS_DIR / "ground_truth.csv"

MAX_TOKENS = 2048
MAX_RETRIES = 2

# V7: F1-F12
ALL_FAULTS_V7 = [f"F{i}" for i in range(1, 13)]

CSV_HEADERS = [...]  # V6과 동일
```

---

## 7. 실험 파라미터

| 항목 | 값 |
|------|-----|
| 실험 버전 | V7 |
| 모델 | gpt-4o-mini |
| 프로바이더 | openai |
| Fault types | F1-F12 (기존 10종 + 신규 2종) |
| Trials per fault | 5 |
| Systems | A, B (paired) |
| 총 RCA 건수 | 120 (60 A + 60 B) — 기존 100 + 신규 20 |
| Collection window | V3과 동일 |
| Cooldown (trial 간) | 60s |
| Cooldown (fault 간) | 900s |

---

## 8. 실행 명령어

### 사전 점검

```bash
# 1. 실험 환경 터널링
# /lab-tunnel 스킬로 수행

# 2. 워커 노드 네트워크 인터페이스 확인 (F11/F12용)
ssh worker01 "ip route | grep default | awk '{print \$5}'"
ssh worker02 "ip route | grep default | awk '{print \$5}'"
ssh worker03 "ip route | grep default | awk '{print \$5}'"

# 3. tc 명령 사용 가능 확인
ssh worker01 "which tc && tc -V"

# 4. RAG KB 최신 상태 확인
python -m src.rag.ingest --reset

# 5. dry-run 테스트 (기존 fault)
python -m experiments.v7.run --dry-run --fault F1 --trial 1

# 6. dry-run 테스트 (신규 fault)
python -m experiments.v7.run --dry-run --fault F11 --trial 1

# 7. Step 3 역추적 검증 dry-run
python -m experiments.v7.run --dry-run --fault F6 --trial 1
python -m experiments.v7.run --dry-run --fault F9 --trial 1
```

### 본 실험

```bash
nohup python -m experiments.v7.run \
  --model gpt-4o-mini \
  --provider openai \
  --cooldown 900 \
  > results/experiment_v7_nohup.log 2>&1 &

echo $! > results/experiment_v7.pid
```

### 실험 재개 (중단 시)

```bash
nohup python -m experiments.v7.run \
  --model gpt-4o-mini \
  --provider openai \
  --cooldown 900 \
  --resume \
  > results/experiment_v7_nohup.log 2>&1 &
```

### 단일 fault 테스트

```bash
# Step 3 역추적 효과 확인
python -m experiments.v7.run --fault F6 --trial 1 --no-preflight
python -m experiments.v7.run --fault F9 --trial 1 --no-preflight

# 네트워크 fault 테스트
python -m experiments.v7.run --fault F11 --trial 1 --no-preflight
python -m experiments.v7.run --fault F12 --trial 1 --no-preflight
```

---

## 9. 예상 소요 시간 및 비용

### 시간 추정

F11/F12 추가로 인해 V6 대비 약 20% 증가.

| 구간 | 시간 |
|------|------|
| 60 trials (12 faults x 5) | ~290min (4h 50min) |
| Fault 간 cooldown (11회 x 900s) | ~165min (2h 45min) |
| comprehensive_health_check 오버헤드 | ~30min |
| **총 예상 시간** | **~8h** |

### 비용 추정

V6과 동일한 호출 패턴, trial 수만 20% 증가.

| 호출 유형 | 건수 | 입력 토큰 (추정) | 출력 토큰 (추정) | 비용 |
|-----------|------|-----------------|-----------------|------|
| Generator | 120 | 5,200 avg | 1,100 avg | $0.18 |
| Evaluator | 120 | 3,000 avg | 300 avg | $0.07 |
| Retry (Generator) | ~36 | 5,500 avg | 1,100 avg | $0.05 |
| Retry (Evaluator) | ~36 | 3,000 avg | 300 avg | $0.02 |
| Correctness Judge | 120 | 500 avg | 200 avg | $0.02 |
| **합계** | | | | **~$0.34** |

---

## 10. 성공 기준

### Primary 기준 (F1-F10 기준, V6 대비)

| 지표 | V6 베이스라인 | V7 목표 (최소) | V7 목표 (기대) |
|------|-------------|---------------|---------------|
| System B 정확도 (F1-F10) | 38% (19/50) | **44% (22/50)** | 52% (26/50) |
| System A 정확도 (F1-F10) | 26% (13/50) | 26% (유지) | 30% |
| B-A 격차 | +12pp | +14pp | +18pp |

### Secondary 기준 (흡수 문제 복원)

F9, F6, F5 중 **2개 이상**에서 V3_B 수준 이상 복원:

| Fault | V3_B | V6_B | V7_B 목표 (최소) |
|-------|------|------|-----------------|
| F9 SecretConfigMap | 80% | 20% | **60%** (V3 대비 -20pp까지 허용) |
| F6 NetworkPolicy | 40% | 0% | **20%** (V3 대비 -20pp까지 허용) |
| F5 PVCPending | 60% | 20% | **40%** (V3 대비 -20pp까지 허용) |

### Safety 기준 (V6 성과 유지)

V6에서 개선된 fault의 정확도가 -20pp 이상 하락하지 않을 것:

| Fault | V6_B | 최소 허용 |
|-------|------|----------|
| F7 DiskPressure | 100% | **80%** |
| F2 CrashLoop | 60% | **40%** |
| F8 ServiceEndpoint | 60% | **40%** |
| F10 ResourceQuota | 60% | **40%** |

### 신규 Fault 기준 (베이스라인 수립)

| Fault | 목표 |
|-------|------|
| F11 NetworkDelay | B >= 20% (첫 베이스라인) |
| F12 NetworkLoss | B >= 20% (첫 베이스라인) |

### 실패 판정 기준

다음 중 하나라도 해당되면 V7 가설 기각:

1. System B 정확도(F1-F10)가 V6 대비 하락 (< 38%)
2. F9/F6/F5 중 **모두** V6과 동일하거나 하락 (흡수 문제 미해결)
3. F7, F2의 V6 성과가 20pp 이상 하락 (Safety 기준 위반)

---

## 11. 리스크 및 완화

### Risk 1: Step 3 역추적이 gpt-4o-mini에게 너무 복잡 (중간)

**메커니즘**: (a)-(d) 4개 하위 점검을 순서대로 수행하라는 지시가 gpt-4o-mini의 reasoning 능력을 초과할 수 있음. 특히 토큰 제한 내에서 모든 하위 점검을 수행하지 못할 위험.

**완화**:
- dry-run에서 F6 t1의 reasoning을 수동 검증하여 역추적 수행 여부 확인
- (a)-(d)는 각각 단순한 yes/no 조건이므로 복잡도가 크지 않음
- 필요 시 (a)-(d)를 3개로 축소 가능 (가장 빈번한 원인 중심)

### Risk 2: 증거 다중성 규칙이 기존 성과를 해침 (낮음)

**메커니즘**: F7(CPU throttle), F10(ResourceQuota)에서 2개 이상 독립 신호를 찾지 못해 confidence를 낮추거나 진단을 변경할 위험.

**완화**:
- F7: `container_cpu_cfs_throttled_periods_total`(메트릭) + `slow response/timeout`(로그) + Pod running(상태) = 3개 독립 신호
- F10: `exceeded quota`(이벤트) + Pod Pending(상태) + `kube_resourcequota` 메트릭 = 3개 독립 신호
- 대부분의 fault는 메트릭+로그+이벤트가 함께 수집되므로 다중 신호 충족

### Risk 3: tc netem이 SSH 복구에 영향 (중간)

**메커니즘**: F11 5s delay나 F12 80% loss가 SSH 세션 자체를 불안정하게 만들어 복구 명령 실행 실패.

**완화**:
- SSH 포트(22) 제외 필터 적용 (W2 안전 조치 참조)
- `at` 명령으로 자동 만료 설정 (10분 후 자동 해제)
- 최악의 경우 노드 재부팅으로 tc 규칙 초기화 가능

### Risk 4: F11/F12 시그널 수집 품질 불확실 (중간)

**메커니즘**: 현재 SignalCollector의 Prometheus 쿼리가 네트워크 지연/손실을 직접 측정하는 메트릭을 수집하지 않을 수 있음. latency histogram은 있지만 노드 레벨 네트워크 메트릭은 확인 필요.

**완화**:
- `node_network_*` 메트릭 수집 여부 사전 확인
- 필요 시 SignalCollector에 네트워크 관련 쿼리 추가 (W2 범위 내)
- F11/F12는 베이스라인 수립이 목적이므로, 낮은 정확도도 허용

### Risk 5: Prometheus port-forward 불안정 (기존)

**완화**: /lab-tunnel 사전 실행, comprehensive_health_check에 모니터링 검증 포함, 중단 시 --resume으로 재개.

---

## 12. 가설 (통계적 형식)

### 주 가설 (H1-main): Step 3 흡수 해결

- **H0**: V7의 System B 정확도(F1-F10) = V6의 System B 정확도 (38%)
- **H1**: V7의 System B 정확도(F1-F10) > V6의 System B 정확도
- **검정**: McNemar test (paired, same fault/trial)
- **유의수준**: alpha = 0.05

### 부 가설 (H1-restore): F9/F6/F5 복원

- **H0**: V7에서 F9/F6/F5의 System B 정답률 합 = V6에서의 합 (40%=20+0+20)
- **H1**: V7에서 F9/F6/F5의 System B 정답률 합 > V6의 합
- **검정**: Wilcoxon signed-rank test (fault-level paired)

### 탐색적 가설

1. Step 3 역추적이 F8(실제 Service endpoint 문제)의 성능을 유지하는가? (역추적 후 fallthrough 경로 검증)
2. 증거 다중성 규칙이 전체 confidence 분포를 어떻게 변화시키는가?
3. F11/F12에서 System B(GitOps+RAG)가 System A보다 유리한가?
4. comprehensive_health_check가 trial 간 간섭을 실제로 감소시키는가?

---

## 13. 인프라 체크리스트

실험 시작 전 확인 사항:

- [ ] `/lab-tunnel` 완료 (K8s API, Prometheus, Loki 접근 확인)
- [ ] `kubectl get nodes -o wide` — 3 worker nodes Ready
- [ ] `kubectl get pods -n boutique` — 모든 pod Running/Ready
- [ ] Prometheus port-forward 안정성 확인 (1분간 3회 쿼리)
- [ ] Loki port-forward 안정성 확인
- [ ] `.env` 파일에 OPENAI_API_KEY 설정 확인
- [ ] RAG KB 최신 상태 (`python -m src.rag.ingest --reset`)
- [ ] `experiments/v7/` 디렉토리 및 모든 파일 존재
- [ ] `results/ground_truth.csv`에 F11/F12 항목 추가 확인
- [ ] 워커 노드 `tc` 명령 사용 가능 확인
- [ ] 워커 노드 네트워크 인터페이스명 확인 및 config에 반영
- [ ] `--dry-run` 성공 (F1 t1, F6 t1, F11 t1 기준)
- [ ] 디스크 여유 공간 확인 (raw JSON 기록용)
- [ ] 이전 실험(V6) 잔여물 없음 확인
- [ ] comprehensive_health_check 단독 실행 테스트 통과

---

## 14. dry-run 검증 계획

코드 구현 후, 본 실험 전 아래 5개 fault에 대해 dry-run + 수동 검증:

1. **F6 t1** (NetworkPolicy — Step 3 흡수 대상): reasoning에 "Step 3(a) Check NetworkPolicy: cilium drops" 언급 여부. "0 endpoints"에서 멈추지 않고 역추적하는지 확인.

2. **F9 t1** (SecretConfigMap — Step 3 흡수 대상): reasoning에 "Step 3(c) Check Secret/ConfigMap: CreateContainerConfigError" 언급 여부. Secret 누락이 0 endpoints의 원인임을 식별하는지 확인.

3. **F8 t1** (ServiceEndpoint — 역추적 후 정상 진단): reasoning에 (a)-(d) 모두 확인 후 "Service Endpoint misconfiguration"으로 확진하는지 확인. 역추적이 F8 성능을 해치지 않는지 검증.

4. **F7 t1** (DiskPressure — 증거 다중성 검증): reasoning에 2개 이상 독립 신호를 인용하는지 확인. 다중성 규칙이 기존 성과에 영향 없는지 검증.

5. **F11 t1** (NetworkDelay — 신규 fault): tc netem 주입 후 시그널 수집 가능 여부 확인. latency 메트릭과 로그가 올바르게 캡처되는지 검증.

---

## 15. 이전 실험 대비 변경 이력

| 버전 | 핵심 변경 | System B 결과 | 교훈 |
|------|-----------|--------------|------|
| V1 | 힌트 제공 + 단순 프롬프트 | 84% | 힌트는 실질적 답을 알려줌 |
| V2 | 힌트 제거 + CoT | 42% | 힌트 없이 gpt-4o-mini 한계 노출 |
| V3 | V2 + Evaluator + Retry + Evidence | 40% | Retry는 B에서만 효과 |
| V4 | V3 + Fault Layer + Context Reranking | 32.5% | 분류 잠금 + 3변수 동시 변경 |
| V5 | V3 + 2단계 분리 (Extraction -> Diagnosis) | 26.5% | 정보 손실 + JSON 불안정 |
| V6 | V3 SYSTEM_PROMPT -> SOP-Guided Prompt | 38% | SOP 직접 매칭 성공, Step 3 흡수 문제 |
| **V7** | **V6 + Step 3 역추적 + 증거 다중성 + F11/F12** | **목표: 44%+** | **흡수 문제 해결 + 실험 범위 확장** |

---

## 16. 실패 시 대안

V7 목표 미달 시 다음 시도할 개선 방향:

1. **Step 3 역추적 간소화**: (a)-(d) 4개가 너무 많으면 가장 효과적인 2개만 유지 (NetworkPolicy + Secret)
2. **Few-shot 역추적 예시**: Step 3에 "0 endpoints → NetworkPolicy가 원인이었던 예시" 1개 추가
3. **증거 다중성 완화**: "2개 필수"를 "2개 권장"으로 약화하여 과도한 제약 방지
4. **F4 NodeNotReady 전용 분석**: V3-V7 전체 실패 원인 심층 조사 (시그널 수집 자체 문제 가능성)
5. **SOP + RAG 연동 강화**: 각 Step에서 해당 fault type 관련 RAG 문서를 선별 주입
