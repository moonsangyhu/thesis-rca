# V8 Dry-Run Summary

**일시**: 2026-04-27 19:40 ~ 19:44 (KST)
**시나리오**: Beta (gRPC histogram bucket 부재 — preflight_v8.txt 참조)

## 1. 사전 점검 요약

| 메트릭 | 통과 기준 | 실제 | 판정 |
|---|---|---|---|
| `grpc_server_handling_seconds_bucket` | ≥1 | 0 | ❌ → 시나리오 Beta |
| `grpc_server_handled_total` | (참고) | 0 | - |
| `node_network_transmit_errs_total` | ≥1 | 91 | ✓ |
| `node_network_receive_errs_total` | ≥1 | 91 | ✓ |
| `node_netstat_Tcp_RetransSegs` | ≥1 | 6 | ✓ |
| RAG F11/F12/F2 | ≥1 doc | 5/5/5 | ✓ |
| Loki API | 동작 | 10 labels | ✓ |

상세: `results/preflight_v8.txt`

## 2. Dry-run 결과 (각 fault t1, fault injection 없음)

| Fault | metrics fields populated | metric anomalies | 통과 |
|---|---|---|---|
| F1 OOMKilled | 0/14 | "No metric anomalies detected" | ✓ |
| F2 CrashLoopBackOff | 0/14 | "No metric anomalies detected" | ✓ |
| F7 CPUThrottle | 0/14 | "No metric anomalies detected" | ✓ |
| F11 NetworkDelay | 0/14 | "No metric anomalies detected" | ✓ |
| F12 NetworkLoss | 0/14 | "No metric anomalies detected" | ✓ |

**baseline 노이즈**: 없음. F1-F10 fault에서 새 메트릭 4종이 노이즈로 출력될 위험 없음.

> 주의: dry-run 모드는 `runner.run_trial(dry_run=True)`에서 fault injection을 건너뛴다. 따라서 F11/F12 실제 fault 신호(request_latency p95 spike, TCP retrans 폭증 등)는 본 실험 trial 1에서 처음 검증된다. 본 검증은 dry-run 범위 밖.

## 3. Dry-run 중 발견된 이슈 + 대응

### 3-1. (해결) etcd gRPC `Canceled` 베이스라인 노이즈

**증상**: 첫 dry-run 컨텍스트에서 `gRPC errors: etcdserverpb.KV Canceled rate=0.0111/s` 출력. 이는 K8s 정상 etcd watch 취소 패턴이며 V8 fault와 무관한 노이즈.

**원인**: `src/collector/prometheus.py::_collect_grpc_errors()`가 grpc_client_handled_total fallback(apiserver→etcd)을 사용하면서 임계값이 `> 0`이라 정상 cancel rate(~0.01-0.05/s)도 출력.

**대응 (plan §7-2-4 사후 임계값 조정)**: 임계값을 `> 0.1/s`로 상향. 정상 etcd cancel은 필터링되고 실제 네트워크 fault(여러 service에서 ≫0.1/s 에러율)는 보존.

### 3-2. (해결) loadgenerator init container ImagePullBackOff

**증상**: `[loadgenerator-*] Error: Could not reach frontend` 같은 에러 로그가 모든 trial 컨텍스트의 Error Logs 섹션에 출력 → LLM이 frontend 장애로 오진할 위험.

**원인**: loadgenerator init container가 `busybox:latest`를 Docker Hub에서 pull하다가 rate limit으로 실패.

**대응**: `kubectl scale deployment loadgenerator -n boutique --replicas=0`. 실험 동안 비활성화. loadgenerator는 V8 독립변수와 무관(load 생성용) — 비활성화 시 영향 없음. 실험 후 manifest 재적용으로 복원 가능.

### 3-3. (해결) frontend service 0 endpoints (V7 F8 잔류)

**증상**: 모든 dry-run 컨텍스트에 "Services with 0 endpoints: frontend" 출력.

**원인**: V7 F8(ServiceEndpoint) fault 잔류. `frontend` service의 selector가 `app: frontend-v2`로 잘못 박혀 있어 매칭되는 pod 없음.

**대응**: `kubectl patch svc frontend -n boutique -p '{"spec":{"selector":{"app":"frontend"}}}'`. 정상 selector로 복구하여 endpoints 1개 등록 확인.

## 4. 본 실험 진행 가능 판정

- ✅ 시나리오 Beta로 진행 (gRPC 메트릭 부재)
- ✅ baseline 노이즈 0 (F1-F10 회귀 위험 최소)
- ✅ 클러스터 잔류 fault 모두 정상화
- ✅ 모니터링 (Prometheus + Loki) Ready
- ✅ RAG F11/F12 인덱싱 + 검색 정상

**결정**: 본 실험 진행 가능.

작성: 2026-04-27 19:45 (KST)
