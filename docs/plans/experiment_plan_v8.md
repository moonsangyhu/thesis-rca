# 실험 계획서: V8 — Network Signal Enrichment (네트워크 신호 보강)

> 작성일: 2026-04-09
> 이전 실험: V7 (SOP + Step 3 Reverse-Tracing + Evidence Multiplicity)
> 분석 근거: `docs/surveys/deep_analysis_v8.md`

---

## 1. 실험 목적

### 1-1. 이전 실험(V7)에서 발견한 문제점

V7은 F1-F10 범위에서 역대 최고 성능(B=46%)을 달성했으나, V7에서 새로 도입한 F11(NetworkDelay)과 F12(NetworkLoss)에서 **A/B 모두 0%**로 완전 실패했다. 원인은 3중 실패 구조로 확인되었다:

1. **RAG 미등록**: `src/rag/config.py`의 `FAULT_TYPES` 딕셔너리에 F11/F12가 없어 `Unknown fault type` 오류 발생. B 시스템이 RAG 없이 실행되어 A와 동일하게 작동.
2. **네트워크 메트릭 미수집**: `src/collector/prometheus.py`가 `cilium_drop_count_total`만 수집. Request latency, gRPC error rate, node network errors, TCP retransmission 등 네트워크 장애 핵심 메트릭이 전혀 없음.
3. **런북 부재**: `docs/runbooks/`에 F11/F12 문서가 없어 RAG가 등록되더라도 검색 대상 자체가 존재하지 않음.

추가로 **클러스터 오염** 문제가 확인되었다. 이전 fault 복구 실패로 `shippingservice CrashLoopBackOff (restarts=28+)` 및 `frontend 0 endpoints`가 F11/F12 trial에 잔류하여, LLM이 이 오염 신호를 보고 "CrashLoopBackOff"로 오진했다.

### 1-2. 이번 실험에서 검증할 개선 사항

**독립변수**: 네트워크 신호 보강 (Network Signal Enrichment)
- Prometheus 네트워크 메트릭 4종 추가 (request latency, gRPC errors, node network errors, TCP retransmission)
- F11/F12 RAG fault type 등록
- F11/F12 런북 문서 작성 및 RAG 인덱싱

**환경 전제조건** (독립변수 아님):
- Fault 타입 전환 시 클러스터 오염 방지를 위한 recovery 강화

### 1-3. System B 성능 향상 목표

- F11 B: 0% -> 60%+ (3/5 이상 정답)
- F12 B: 0% -> 60%+ (3/5 이상 정답)
- 전체 B (F1-F12): 38% -> 48%+ (+10pp 이상)
- F1-F10 B: 46% 유지 (회귀 없음)

---

## 2. 이전 결과 분석 요약

### 2-1. 전체 정답률 (V7)

| 시스템 | F1-F10 | F11-F12 | 전체 (F1-F12) |
|--------|--------|---------|---------------|
| System A | 26% (13/50) | 0% (0/10) | 22% (13/60) |
| System B | 46% (23/50) | 0% (0/10) | 38% (23/60) |
| B-A 차이 | +20pp | 0pp | +16pp |

### 2-2. Fault Type별 성과 (V7 B)

| Fault | A | B | 비고 |
|-------|---|---|------|
| F1 OOMKilled | 2/5 (40%) | 1/5 (20%) | B 열위 - RAG 오도 (CPU throttle 방향) |
| F2 CrashLoopBackOff | 0/5 (0%) | 5/5 (100%) | B 최대 수혜 - RAG 런북 |
| F3 ImagePullBackOff | 3/5 (60%) | 3/5 (60%) | A=B 동일 |
| F4 NodeNotReady | 0/5 (0%) | 0/5 (0%) | 구조적 실패 - 신호 수집 시점 이슈 |
| F5 PVCPending | 2/5 (40%) | 2/5 (40%) | A=B 동일, V3(60%) 대비 퇴행 |
| F6 NetworkPolicy | 0/5 (0%) | 2/5 (40%) | B 우위 - GitOps diff로 정책 확인 |
| F7 CPUThrottle | 2/5 (40%) | 3/5 (60%) | B 소폭 우위 |
| F8 ServiceEndpoint | 0/5 (0%) | 2/5 (40%) | B 우위 - GitOps diff로 selector 확인 |
| F9 SecretConfigMap | 2/5 (40%) | 2/5 (40%) | V3(80%) 대비 퇴행 |
| F10 ResourceQuota | 2/5 (40%) | 3/5 (60%) | B 소폭 우위 |
| **F11 NetworkDelay** | **0/5 (0%)** | **0/5 (0%)** | **3중 실패: RAG+메트릭+런북 부재** |
| **F12 NetworkLoss** | **0/5 (0%)** | **0/5 (0%)** | **3중 실패: 동일** |

### 2-3. 핵심 실패 원인 Top 3

1. **F11/F12 3중 실패** (20건 모두 오답): RAG 미등록 + 네트워크 메트릭 미수집 + 런북 부재. Raw context에 네트워크 관련 신호가 0건이므로 LLM이 진단 불가.
2. **클러스터 오염** (F11/F12 + F4 일부): 이전 fault 복구 잔류물(`shippingservice CrashLoopBackOff`, `frontend 0 endpoints`)이 다음 trial에 잔류. LLM이 오염 신호를 실제 장애로 오인.
3. **F4 시간적 신호 부재** (10건 모두 오답): 노드 복구 후 수집 시점에 이미 Ready 상태로 복귀하여 NodeNotReady 신호가 없음. 이 문제는 V8 범위 밖.

### 2-4. System B가 A보다 못한 케이스

F1 trial 1에서만 B가 A보다 열위 (A=정답, B=오답). B의 RAG 컨텍스트가 CPU throttle 방향으로 오도한 것으로 분석. 총 60 trial 중 B 퇴행은 1건뿐이므로 RAG 노이즈 리스크는 매우 낮다.

---

## 3. 개선 사항 상세

### 3-1. [독립변수] src/rag/config.py - F11/F12 FAULT_TYPES 추가

**변경 전** (현재 코드, L37-89):
```python
# Fault type mapping (F1~F10)
FAULT_TYPES = {
    "F1": {...},
    ...
    "F10": {...},
}
```

**변경 후**:
```python
# Fault type mapping (F1~F12)
FAULT_TYPES = {
    "F1": {...},
    ...
    "F10": {...},
    "F11": {
        "name": "NetworkDelay",
        "description": "Network latency injected via tc netem causing service timeouts and gRPC deadline exceeded errors",
        "keywords": ["NetworkDelay", "latency", "delay", "timeout", "deadline", "netem", "tc", "slow", "p95", "p99"],
    },
    "F12": {
        "name": "NetworkLoss",
        "description": "Packet loss injected via tc netem causing intermittent connection failures and TCP retransmissions",
        "keywords": ["NetworkLoss", "packet loss", "retransmission", "TCP", "reset", "broken pipe", "EOF", "connection reset"],
    },
}
```

**수정 파일**: `src/rag/config.py` L37 주석 변경, L89 뒤에 F11/F12 항목 추가
**예상 효과**: RAG retriever가 F11/F12에 대해 `Unknown fault type` 오류 없이 정상 검색 가능. B 시스템이 런북 기반 감별 진단 가능.

### 3-2. [독립변수] src/collector/prometheus.py - 네트워크 메트릭 4종 추가

**변경 전**: `collect()` 메서드(L61-81)가 10개 메트릭만 수집. 네트워크 관련은 `network_drops` (cilium_drop_count_total)뿐.

**변경 후**: `collect()` 메서드에 4종 추가:

```python
def collect(self, namespace: str = TARGET_NAMESPACE, window_minutes: int = 5) -> dict:
    now = time.time()
    start = now - (window_minutes * 60)
    return {
        # ... 기존 10개 유지 ...
        "network_drops": self._collect_network_drops(namespace),
        # 신규 4종
        "request_latency": self._collect_request_latency(namespace),
        "grpc_errors": self._collect_grpc_errors(namespace),
        "network_errors": self._collect_network_errors(),
        "tcp_retransmissions": self._collect_tcp_retrans(),
    }
```

**신규 메서드 4개**:

```python
def _collect_request_latency(self, ns: str) -> list[dict]:
    """gRPC/HTTP request latency p95 > 500ms."""
    data = self._query(
        'histogram_quantile(0.95, '
        'sum(rate(grpc_server_handling_seconds_bucket[5m])) by (le, grpc_service, grpc_method)'
        ') > 0.5'
    )
    return [
        {
            "service": item["metric"].get("grpc_service", ""),
            "method": item["metric"].get("grpc_method", ""),
            "p95_seconds": round(float(item["value"][1]), 3),
        }
        for item in data
    ]

def _collect_grpc_errors(self, ns: str) -> list[dict]:
    """gRPC non-OK response rates."""
    data = self._query(
        'sum(rate(grpc_server_handled_total{grpc_code!="OK"}[5m])) '
        'by (grpc_service, grpc_code) > 0'
    )
    return [
        {
            "service": item["metric"].get("grpc_service", ""),
            "code": item["metric"].get("grpc_code", ""),
            "rate": round(float(item["value"][1]), 4),
        }
        for item in data
    ]

def _collect_network_errors(self) -> list[dict]:
    """Node-level network transmit/receive errors."""
    results = []
    for direction in ("transmit", "receive"):
        data = self._query(
            f'rate(node_network_{direction}_errs_total{{device!~"lo|veth.*|lxc.*|cilium.*"}}[5m]) > 0'
        )
        for item in data:
            results.append({
                "node": item["metric"].get("instance", ""),
                "device": item["metric"].get("device", ""),
                "direction": direction,
                "error_rate": round(float(item["value"][1]), 4),
            })
    return results

def _collect_tcp_retrans(self) -> list[dict]:
    """TCP retransmission rate per node."""
    data = self._query(
        'rate(node_netstat_Tcp_RetransSegs[5m]) > 0'
    )
    return [
        {
            "node": item["metric"].get("instance", ""),
            "retrans_rate": round(float(item["value"][1]), 2),
        }
        for item in data
    ]
```

**수정 파일**: `src/collector/prometheus.py`
- L70-81: `collect()` 메서드에 4개 키 추가
- L269 이후: 4개 신규 메서드 추가

**예상 효과**:
- F11(NetworkDelay): `request_latency` p95 > 500ms 감지, `grpc_errors` DeadlineExceeded 감지
- F12(NetworkLoss): `network_errors` transmit/receive errors 감지, `tcp_retransmissions` 이상치 감지, `grpc_errors` Unavailable/Internal 감지

**리스크 및 대응**:
- gRPC 메트릭이 scrape되지 않을 수 있음 -> dry-run에서 Prometheus 직접 쿼리로 확인. 미수집 시 node-exporter 메트릭만으로 대체.
- 일부 메트릭이 빈 결과를 반환할 수 있음 -> 빈 결과는 기존 로직대로 무시되므로 부작용 없음.

### 3-3. [독립변수] src/processor/context_builder.py - 네트워크 메트릭 포맷팅

**변경 전**: `_build_metric_anomalies()` (L169-224)에서 network_drops만 포맷팅.

**변경 후**: `_build_metric_anomalies()`에 4개 섹션 추가:

```python
def _build_metric_anomalies(self, metrics: dict) -> str:
    parts = []
    # ... 기존 OOM, CPU throttle, memory, endpoints, PVC, quota, network drops 유지 ...

    # Request latency (신규)
    latency = metrics.get("request_latency", [])
    if latency:
        parts.append("Request latency (p95): " + ", ".join(
            f"{l['service']}/{l['method']} {l['p95_seconds']:.1f}s"
            for l in latency
        ))

    # gRPC errors (신규)
    grpc_err = metrics.get("grpc_errors", [])
    if grpc_err:
        parts.append("gRPC errors: " + ", ".join(
            f"{g['service']} {g['code']} rate={g['rate']:.3f}/s"
            for g in grpc_err
        ))

    # Node network errors (신규)
    net_err = metrics.get("network_errors", [])
    if net_err:
        parts.append("Node network errors: " + ", ".join(
            f"{n['node']} {n['device']} {n['direction']}_errs rate={n['error_rate']:.3f}/s"
            for n in net_err
        ))

    # TCP retransmissions (신규)
    tcp_retrans = metrics.get("tcp_retransmissions", [])
    if tcp_retrans:
        parts.append("TCP retransmissions: " + ", ".join(
            f"{t['node']} retrans rate={t['retrans_rate']:.1f}/s"
            for t in tcp_retrans
        ))

    return "\n".join(parts) if parts else "No metric anomalies detected."
```

**수정 파일**: `src/processor/context_builder.py` L169-224
**예상 효과**: LLM에 "Request latency (p95): frontend/server 1.2s", "TCP retransmissions: worker01 rate=120.0/s" 등 명시적 네트워크 이상 텍스트가 제공됨. SOP Step 4 ("Check Network: abnormal latency >500ms, packet loss indicators")에서 매칭 가능.

### 3-4. [독립변수] docs/runbooks/rca-f11-networkdelay.md - F11 런북

기존 런북(`rca-f6-networkpolicy.md` 등)과 동일한 형식으로 작성. 핵심 내용:

```markdown
# Runbook: F11 - Network Delay (tc netem) Root Cause Analysis

## Trigger Conditions
Use this runbook when services show increased latency (p95 > 500ms), gRPC deadline
exceeded errors, intermittent timeouts across multiple services on the same node, or
TCP retransmission rates spike. Applies when traffic shaping (tc netem) may have been
applied to a node's network interface.

## Severity
**High** - Network delay causes cascading timeouts across all services on the affected
node, leading to gRPC DeadlineExceeded, HTTP gateway timeouts, and potential health
check failures.

## Key Differentiators (vs other faults)
- **vs F6 (NetworkPolicy)**: F11 shows high latency but connections eventually succeed
  (unless timeout). F6 shows immediate connection refused/dropped. F11 affects ALL
  traffic on the node; F6 affects specific service pairs.
- **vs F4 (NodeNotReady)**: F11 node remains Ready but slow. F4 node becomes NotReady.
- **vs F7 (CPUThrottle)**: F11 latency is network-layer (affects all services on node
  uniformly). F7 latency is application-layer (affects specific throttled container).

## Investigation Steps
1. Check request latency: p95/p99 > 500ms across services on same node
2. Check gRPC errors: DeadlineExceeded rate increase
3. Check node network metrics: transmit/receive errors, TCP retransmissions
4. Verify tc qdisc: `tc -s qdisc show dev <interface>` on suspected node
5. Check which node is affected: correlate high-latency services with node placement

## Expected Signals
- Metric: `grpc_server_handling_seconds p95 > 0.5s` (multiple services on same node)
- Metric: `grpc_server_handled_total{grpc_code="DeadlineExceeded"}` rate > 0
- Metric: `node_netstat_Tcp_RetransSegs` rate elevated on affected node
- Log: "context deadline exceeded", "i/o timeout", "connection timed out"
- Node: All nodes show Ready (unlike F4 NodeNotReady)

## Recovery
tc qdisc del dev <interface> root
```

**수정 파일**: `docs/runbooks/rca-f11-networkdelay.md` (신규 생성)

### 3-5. [독립변수] docs/runbooks/rca-f12-networkloss.md - F12 런북

```markdown
# Runbook: F12 - Network Packet Loss (tc netem) Root Cause Analysis

## Trigger Conditions
Use this runbook when services show intermittent connection failures, TCP resets,
"broken pipe" or "EOF" errors, high retransmission rates, or fluctuating error rates
that correlate with a specific node.

## Severity
**High to Critical** - Packet loss causes intermittent failures that are harder to
diagnose than complete outages. High loss rates (>30%) make services effectively
unavailable.

## Key Differentiators (vs other faults)
- **vs F11 (NetworkDelay)**: F12 shows connection resets and EOF errors (packets
  dropped). F11 shows timeouts (packets delayed). F12 has more intermittent pattern.
- **vs F6 (NetworkPolicy)**: F12 shows random failures (some succeed, some fail).
  F6 shows consistent blocking. F12 shows TCP retransmissions; F6 shows cilium drops.
- **vs F2 (CrashLoopBackOff)**: F12 affects multiple services on same node.
  F2 affects single service. F12 pods stay Running; F2 pods restart.

## Investigation Steps
1. Check gRPC error rates: non-OK codes across services on same node
2. Check TCP retransmissions: rate spike on affected node
3. Check node network errors: transmit/receive error rates
4. Check error patterns: "connection reset", "broken pipe", "EOF" in logs
5. Verify tc qdisc: `tc -s qdisc show dev <interface>` on suspected node

## Expected Signals
- Metric: `grpc_server_handled_total{grpc_code!="OK"}` rate > 0 (multiple services)
- Metric: `node_netstat_Tcp_RetransSegs` rate highly elevated
- Metric: `node_network_transmit_errs_total` or `receive_errs_total` rate > 0
- Log: "connection reset by peer", "broken pipe", "EOF", "transport is closing"
- Node: All nodes show Ready

## Recovery
tc qdisc del dev <interface> root
```

**수정 파일**: `docs/runbooks/rca-f12-networkloss.md` (신규 생성)

### 3-6. [독립변수] experiments/v8/ - V7 복사 + config 변경

V7 디렉토리를 복사하여 V8 생성. 변경 사항:

| 파일 | 변경 내용 |
|------|----------|
| `experiments/v8/__init__.py` | 복사 |
| `experiments/v8/config.py` | 경로를 v8로 변경 (CSV, RAW_DIR, log 등) |
| `experiments/v8/engine.py` | `RCAEngineV7` -> `RCAEngineV8` (클래스명만 변경, 로직 동일) |
| `experiments/v8/prompts.py` | V7과 **완전 동일** (프롬프트 변경 없음) |
| `experiments/v8/run.py` | import 경로를 v8로 변경, 로그 메시지 v8으로 변경 |

**config.py 변경 내용**:
```python
"""v8 experiment configuration: Network Signal Enrichment (V7 fork)."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
RESULTS_DIR = PROJECT_ROOT / "results"
RESULTS_CSV = RESULTS_DIR / "experiment_results_v8.csv"
RAW_DIR = RESULTS_DIR / "raw_v8"
GROUND_TRUTH_CSV = RESULTS_DIR / "ground_truth.csv"

MAX_TOKENS = 2048
MAX_RETRIES = 2

CSV_HEADERS = [...]  # V7과 동일
```

**주의**: 프롬프트는 V7과 완전히 동일하게 유지한다. V8의 독립변수는 "네트워크 신호 보강"이지 프롬프트 변경이 아니다. SOP Step 4에 이미 "abnormal latency (>500ms), packet loss indicators"가 포함되어 있으므로, 새 메트릭이 컨텍스트에 나타나면 기존 프롬프트로도 매칭 가능하다.

### 3-7. [환경 전제조건] scripts/stabilize/recovery.py - 오염 방지 강화

**변경 목적**: 실험 변수가 아닌 환경 정상화. Fault 타입 전환 시 클러스터 오염을 방지한다.

**변경 내용**:
- `_full_reset()` 메서드에 `kubectl rollout restart deployment --all` 추가 (manifest re-apply 후 모든 pod 강제 재시작)
- `_wait_for_healthy()` 메서드에 endpoint 검증 추가 (모든 서비스 endpoint > 0 확인)
- `_cleanup_failed_pods()` 범위 확장: `Evicted`, `Error` 상태 pod도 정리

```python
def _full_reset(self) -> dict:
    """Nuclear option: re-apply original manifests + force restart all."""
    logger.info("Full reset: re-applying original manifests + restart all")
    result = kubectl("apply", "-f", ORIGINAL_MANIFEST, namespace=NAMESPACE)
    # Force restart to clear any stale container state
    kubectl("rollout", "restart", "deployment", "--all", namespace=NAMESPACE)
    return {"action": "full_reset", "output": result}
```

### 3-8. [환경 전제조건] scripts/stabilize/health_verify.py - SSH key 전달 수정

V7에서 발견된 SSH key 전달 문제를 수정하여 disk usage 체크가 정상 작동하도록 한다. 구체적 수정 내용은 `ssh_node()` 호출 시 key 경로 명시.

### 3-9. [환경 전제조건] RAG 재인덱싱

F11/F12 런북 추가 후 반드시 RAG 인덱스를 재구축한다:

```bash
python -m src.rag.ingest
```

이를 통해 ChromaDB에 F11/F12 런북이 인덱싱되어 검색 가능해진다.

---

## 4. 통제 변수 (변경하지 않는 것)

| 항목 | 파일 | 설명 |
|------|------|------|
| 프롬프트 | `experiments/v8/prompts.py` | V7 SOP 프롬프트 완전 동일 |
| 엔진 로직 | `experiments/v8/engine.py` | RCAEngineV7 로직 그대로 복사 |
| LLM 모델 | gpt-4o-mini | 고정 |
| Evaluator | V7 EVALUATOR_PROMPT | 동일 |
| Retry 로직 | MAX_RETRIES=2 | 동일 |
| Evidence Verification | `_verify_evidence()` | 동일 |
| Correctness Judge | `judge_correctness()` | 동일 |
| F1-F10 fault injection | `scripts/fault_inject/` | 변경 없음 |
| F1-F10 recovery | `scripts/stabilize/recovery.py` | per-fault 로직 변경 없음 |
| 평가 방식 | ground_truth.csv + judge | 동일 |

---

## 5. 실험 파라미터

| 파라미터 | 값 | 비고 |
|---------|---|------|
| 실험 버전 | V8 | |
| 모델 | gpt-4o-mini | 고정 |
| 프로바이더 | openai | |
| Fault types | F1-F12 | 12종 |
| Trials per fault | 5 | |
| 총 trials | 120 (A+B) = 60 pairs | |
| Collection window | 5분 | Prometheus range query 윈도우 |
| INJECTION_WAIT | fault별 상이 | F11/F12는 60초 (netem 적용 후 효과 전파) |
| Cooldown (fault 간) | 900초 (15분) | fault 타입 전환 시 |
| Cooldown (trial 간) | 60초 | 동일 fault 내 trial 전환 시 |
| MAX_TOKENS | 2048 | LLM 출력 토큰 |
| MAX_RETRIES | 2 | Evaluator 기반 재시도 |
| TOP_K (RAG) | 5 | RAG 검색 문서 수 |

---

## 6. 코드 수정 체크리스트

### 독립변수 (반드시 수정)

- [ ] `src/rag/config.py` L37 주석 "F1~F10" -> "F1~F12", L89 뒤에 F11/F12 항목 추가
- [ ] `src/collector/prometheus.py` L70-81 `collect()` 메서드에 4개 키 추가
- [ ] `src/collector/prometheus.py` L269 뒤에 `_collect_request_latency()`, `_collect_grpc_errors()`, `_collect_network_errors()`, `_collect_tcp_retrans()` 4개 메서드 추가
- [ ] `src/processor/context_builder.py` L169-224 `_build_metric_anomalies()` 메서드에 4개 포맷팅 섹션 추가
- [ ] `docs/runbooks/rca-f11-networkdelay.md` 신규 생성
- [ ] `docs/runbooks/rca-f12-networkloss.md` 신규 생성
- [ ] `experiments/v8/` 디렉토리 생성 (V7 복사 기반)
- [ ] `experiments/v8/config.py` 경로를 v8로 변경
- [ ] `experiments/v8/engine.py` 클래스명 RCAEngineV8로 변경
- [ ] `experiments/v8/run.py` import 경로 v8로 변경

### 환경 전제조건 (독립변수 아님)

- [ ] `scripts/stabilize/recovery.py` `_full_reset()` 메서드에 rollout restart 추가
- [ ] `scripts/stabilize/recovery.py` `_wait_for_healthy()` 메서드에 endpoint 검증 추가
- [ ] `scripts/stabilize/health_verify.py` SSH key 전달 수정
- [ ] RAG 재인덱싱: `python -m src.rag.ingest`

### 검증 (dry-run 전)

- [ ] Prometheus 메트릭 가용성 확인 (lab-tunnel 후 직접 쿼리)
- [ ] RAG F11/F12 검색 확인: `retriever.query_by_fault('F11')` 결과 확인
- [ ] dry-run 테스트 통과

---

## 7. 실행 명령어

### 7-1. 사전 점검

```bash
# 1. 실험 환경 터널 연결
/lab-tunnel

# 2. Prometheus 네트워크 메트릭 가용성 확인
# gRPC 메트릭 존재 확인
curl -s "http://localhost:9090/api/v1/query?query=grpc_server_handling_seconds_bucket" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'gRPC metrics: {len(d[\"data\"][\"result\"])} series')"

# node-exporter 네트워크 메트릭 확인
curl -s "http://localhost:9090/api/v1/query?query=node_network_transmit_errs_total" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Network error metrics: {len(d[\"data\"][\"result\"])} series')"

# TCP retransmission 메트릭 확인
curl -s "http://localhost:9090/api/v1/query?query=node_netstat_Tcp_RetransSegs" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'TCP retrans metrics: {len(d[\"data\"][\"result\"])} series')"

# 3. RAG 재인덱싱
python -m src.rag.ingest

# 4. RAG F11/F12 검색 확인
python3 -c "
from src.rag.retriever import KnowledgeRetriever
r = KnowledgeRetriever()
for fid in ('F11', 'F12'):
    results = r.query_by_fault(fid)
    print(f'{fid}: {len(results)} docs retrieved')
    for doc in results[:2]:
        print(f'  - {doc[\"metadata\"].get(\"source\", \"?\")} (score={doc.get(\"score\", \"?\")})')
"
```

### 7-2. dry-run 테스트

```bash
# F11 단일 trial dry-run
python -m experiments.v8.run --dry-run --fault F11 --trial 1

# F12 단일 trial dry-run
python -m experiments.v8.run --dry-run --fault F12 --trial 1

# F1 단일 trial dry-run (회귀 확인)
python -m experiments.v8.run --dry-run --fault F1 --trial 1
```

### 7-3. 본 실험

```bash
# 전체 실험 실행 (F1-F12 x 5 trials = 60 pairs)
nohup python -m experiments.v8.run > results/experiment_v8_nohup.log 2>&1 &
echo $! > results/experiment_v8.pid

# 진행 상황 모니터링
tail -f results/experiment_v8.log
```

### 7-4. 부분 실행 (필요 시)

```bash
# F11/F12만 먼저 실행 (핵심 검증)
python -m experiments.v8.run --fault F11
python -m experiments.v8.run --fault F12

# 나머지 F1-F10 (회귀 확인)
python -m experiments.v8.run --resume
```

---

## 8. 예상 소요 시간 및 비용

### 시간

| 단계 | 시간 |
|------|------|
| 코드 수정 + 런북 작성 | 1-2시간 |
| RAG 재인덱싱 | 5분 |
| Prometheus 메트릭 확인 | 15분 |
| dry-run 테스트 | 15분 |
| 본 실험 (60 pairs) | 10-14시간 |
| 결과 분석 | 30분 |
| **합계** | **~12-17시간** |

### API 비용 (추정)

| 항목 | 산출 근거 | 비용 |
|------|----------|------|
| Generator 호출 | 120 trials x ~3K tokens/call | ~$0.72 |
| Evaluator 호출 | 120 trials x ~2K tokens/call | ~$0.48 |
| Retry 호출 | ~40 retries x ~3K tokens/call | ~$0.24 |
| Correctness Judge | 120 trials x ~1K tokens/call | ~$0.24 |
| **합계** | | **~$1.70** |

(gpt-4o-mini: $0.15/1M input, $0.60/1M output 기준)

---

## 9. 예상 결과

### 9-1. Fault별 예상 정확도

| Fault | V7 A | V7 B | V8 B (예상) | 변화 | 근거 |
|-------|------|------|------------|------|------|
| F1 OOMKilled | 40% | 20% | 20-40% | 0~+20pp | 새 메트릭이 OOM 진단에 간접 도움 가능 |
| F2 CrashLoopBackOff | 0% | 100% | 100% | 유지 | 변경 없음 |
| F3 ImagePullBackOff | 60% | 60% | 60% | 유지 | 변경 없음 |
| F4 NodeNotReady | 0% | 0% | 0-20% | 0~+20pp | 오염 제거로 미세 개선 가능하나 구조적 한계 |
| F5 PVCPending | 40% | 40% | 40% | 유지 | 변경 없음 |
| F6 NetworkPolicy | 0% | 40% | 40-60% | 0~+20pp | 네트워크 메트릭이 감별 진단 보조 가능 |
| F7 CPUThrottle | 40% | 60% | 60% | 유지 | 변경 없음 |
| F8 ServiceEndpoint | 0% | 40% | 40% | 유지 | 변경 없음 |
| F9 SecretConfigMap | 40% | 40% | 40% | 유지 | V8 범위 밖 (V9 후보) |
| F10 ResourceQuota | 40% | 60% | 60% | 유지 | 변경 없음 |
| **F11 NetworkDelay** | **0%** | **0%** | **60-80%** | **+60-80pp** | **메트릭+RAG+런북 3중 보강** |
| **F12 NetworkLoss** | **0%** | **0%** | **60-80%** | **+60-80pp** | **동일** |

### 9-2. 전체 정확도 예상

| 범위 | V7 B | V8 B (보수적) | V8 B (낙관적) |
|------|------|--------------|--------------|
| F1-F10 | 46% (23/50) | 46% (23/50) | 50% (25/50) |
| F11-F12 | 0% (0/10) | 60% (6/10) | 80% (8/10) |
| **전체 F1-F12** | **38% (23/60)** | **48% (29/60)** | **55% (33/60)** |

### 9-3. 통계적 유의성 예상

보수적 시나리오(B=48%)에서도 V7 B(38%) 대비 +10pp 개선. F11/F12 10 trial에서 0->6건 변화는 McNemar's test에서 p < 0.05 예상 (discordant pairs = 6, all in same direction).

---

## 10. 성공 기준

### 주 기준 (필수)

1. **F11 B 정답률 >= 40%** (2/5 이상) — 0%에서의 유의미한 개선
2. **F12 B 정답률 >= 40%** (2/5 이상) — 동일
3. **전체 B 정답률 >= 45%** (27/60 이상) — V7(38%) 대비 +7pp 이상
4. **F1-F10 B 정답률 >= 42%** (21/50 이상) — V7(46%) 대비 4pp 이내 하락 허용 (회귀 허용 범위)

### 부 기준 (바람직)

5. F11 B 정답률 >= 60% (3/5)
6. F12 B 정답률 >= 60% (3/5)
7. 전체 B 정답률 >= 48% (29/60)
8. B > A 차이가 F1-F12 전체에서 유지

### 실패 판정 기준

- F11+F12 B 합산 0% (개선 없음) -> V8 독립변수가 효과 없음
- F1-F10 B < 38% (V7 대비 8pp 이상 하락) -> 회귀 발생, 원인 분석 필요

---

## 11. 리스크 및 대응

### 리스크 1: gRPC 메트릭 미수집

**가능성**: 중 (kube-prometheus-stack 기본 설정에서 gRPC 메트릭이 scrape 대상이 아닐 수 있음)
**영향**: `_collect_request_latency()`, `_collect_grpc_errors()` 빈 결과 반환
**대응**:
1. dry-run 전 Prometheus 직접 쿼리로 확인
2. 미수집 시 ServiceMonitor 추가 (`kubectl apply -f` 로 Online Boutique 서비스에 ServiceMonitor 추가)
3. 최악의 경우 node-exporter 메트릭(`network_errors`, `tcp_retransmissions`)만으로도 F11/F12 진단 가능한지 확인

### 리스크 2: tc netem의 kubelet 통신 지연

**가능성**: 중-높 (tc netem은 노드의 모든 네트워크 트래픽에 적용)
**영향**: F11 trial에서 kubelet 하트비트 지연 -> 노드 NotReady -> F4-like 부작용
**대응**:
1. F11 trial 5 (delay=5000ms) 이 특히 위험. 이 경우 노드가 NotReady가 되면 ground truth의 예상 동작과 일치하므로 진단이 어려워짐
2. 수집 시점에 노드 상태를 확인하고, NotReady가 발생하면 로그에 기록
3. 해당 trial은 "mixed fault" 특성을 분석 리포트에 기록

### 리스크 3: F11/F6 혼동

**가능성**: 중 (둘 다 네트워크 관련 장애)
**영향**: LLM이 F11을 NetworkPolicy로 오진
**대응**:
1. F11 런북에 "vs F6" 감별 포인트 명시 (latency vs connection refused)
2. F11 컨텍스트에서 cilium_drop이 없으면 F6 가능성 배제 근거가 됨
3. SOP Step 4가 이미 NetworkPolicy와 delay를 구분하는 구조

### 리스크 4: 클러스터 오염 재발

**가능성**: 낮 (recovery 강화로 대응)
**영향**: F11/F12 trial에 이전 fault 잔류물이 남아 있으면 V7과 동일한 실패
**대응**:
1. `comprehensive_health_check()`가 endpoint 검증 포함
2. 오염이 감지되면 `_full_reset()` + rollout restart 수행
3. 로그에서 "remaining_issues" 확인하여 오염 trial 식별

---

## 12. 통계 검정 계획

### 12-1. 주 검정: V8 B vs V7 B (McNemar's test)

같은 (fault, trial) 쌍에 대해 V7 B와 V8 B의 정답/오답을 paired로 비교.

| | V8 B 정답 | V8 B 오답 |
|---|-----------|-----------|
| V7 B 정답 | a | b |
| V7 B 오답 | c | d |

McNemar chi-squared = (b - c)^2 / (b + c), H0: b = c
예상: c >> b (V7 오답이 V8에서 정답으로 전환), 특히 F11/F12에서.

### 12-2. 부 검정: F11/F12 subset (Fisher's exact test)

F11/F12 10 trial만 추출하여 V7 B vs V8 B 비교.
V7: 0/10, V8 예상: 6-8/10 -> Fisher's exact p < 0.01 예상.

### 12-3. 주 가설 검정: V8 A vs V8 B (Wilcoxon signed-rank test)

논문의 주 가설 "System B > System A"를 V8 데이터로도 검정.
V8에서 A는 네트워크 메트릭을 받지만 RAG/런북은 없으므로, B가 A보다 높을 것으로 예상.

**주의**: F11/F12에서 A도 네트워크 메트릭을 받으므로 A의 정확도도 0%에서 일부 개선될 수 있음. B와의 차이는 RAG 런북 효과로 측정.

### 12-4. 회귀 검정: F1-F10 V7 B vs V8 B

F1-F10 50 trial에서 V7 B와 V8 B가 유의미하게 다르지 않음을 확인 (비열등성).
McNemar's test에서 p > 0.05이면 회귀 없음으로 판정.

---

## 13. 실패 시 대안

### 시나리오 A: gRPC 메트릭 전혀 없음

node-exporter 메트릭만으로 실험 진행. `_collect_request_latency()`와 `_collect_grpc_errors()`를 fallback 쿼리로 대체:
- `rate(node_network_receive_bytes_total[5m])` 이상치로 간접 감지
- pod log에서 "deadline exceeded", "timeout" 패턴 매칭 강화

### 시나리오 B: F11/F12 개선 없음 (0% 유지)

1. Raw context를 분석하여 네트워크 메트릭이 실제로 수집되었는지 확인
2. 수집되었으나 LLM이 무시한 경우 -> V9에서 프롬프트 강화 (Step 4 네트워크 진단 세분화)
3. 수집 자체가 실패한 경우 -> Prometheus scrape config 확인, ServiceMonitor 추가

### 시나리오 C: F1-F10 회귀 발생

1. 새 메트릭이 노이즈로 작용했는지 확인 (정상 상태에서도 네트워크 메트릭이 출력되는지)
2. 노이즈가 확인되면 threshold 조정 (e.g., TCP retrans rate > 10 으로 상향)
3. 최악의 경우 F1-F10에서는 새 메트릭을 출력하지 않도록 조건부 포맷팅

---

## 14. 참조 문헌

| 논문/자료 | 핵심 기법 | V8 적용 |
|----------|----------|---------|
| SynergyRCA (arxiv:2506.02490) | StateGraph + LLM for K8s RCA | 엔티티 관계를 컨텍스트에 포함하는 아이디어 참조 |
| gRPC OpenTelemetry Metrics Guide (grpc.io) | `grpc.server.call.duration`, `grpc.client.attempt.duration` | gRPC 메트릭 쿼리 설계 근거 |
| Modern K8s Monitoring: Metrics, Tools, and AIOps (Red Hat, 2025) | Prometheus + synthetic probes for packet loss, latency 측정 | node-exporter 네트워크 메트릭 활용 근거 |
| LLMRCA: Multilevel RCA Using Multimodal Observability (ACM, 2025) | 다중 신호 소스 결합으로 RCA 정확도 향상 | Signal Enrichment Principle: RAG + 신호 + 런북 3중 결합 필요성의 문헌적 근거 |

---

## 15. V9 후속 실험 후보 (참고)

V8 결과에 따라 다음 중 하나를 V9에서 시도:

1. **F9 역추적 강화**: SOP Step 2에서 CreateContainerConfigError 검출 시 Secret/ConfigMap 우선 검사. V3(80%) -> V7(40%) 퇴행 복구 목표.
2. **F4 시계열 수집**: 노드 장애 이력(recent events with "NotReady")을 Prometheus alert history나 Kubernetes event stream에서 회고적으로 수집. 수집 시점 이후 복구된 노드도 진단 가능하게.
3. **Evaluator 판별력 개선**: 현재 evaluator가 정답/오답 판별력이 거의 없음 (차이 < 0.3점). Few-shot 예제 추가 또는 scoring rubric 세분화.
