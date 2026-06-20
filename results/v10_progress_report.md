# V10 실험 진행 보고서 (re-baseline)

> 작성: 2026-06-20 · 상태: **실행 완료(F1–F10) / F11–F12 주입 실패 / 미커밋·미분석**
> 근거: `results/experiment_results_v10.csv`, `results/experiment_v10.log`, `experiments/v10/`, `.hermes/handoffs/2026-06-19-infra-rebuild-and-v10-rebaseline.md`
> ⚠️ 본 문서는 **중간 진행 보고서**이며 정식 분석(`results/analysis_v10.md`)이 아니다. 통계 검정·가설 판정은 미수행.

---

## 0. 한눈에 보기

| 항목 | 내용 |
|---|---|
| 실험 정체성 | **V10 = re-baseline.** 재구축된 K8s 클러스터에서 baseline을 처음부터 다시 수집 |
| 코드 베이스 | V9 프레임워크 유지 (System A/B, RAG, F1–F12, **V9 Pre-Trial State Validator 포함**) |
| 변경된 것 | 데이터만 새 환경에서 재수집. RCA 로직·프롬프트·모델은 불변 |
| 모델 | `gpt-4o-mini` 고정 (전 100행 동일) |
| 실행 시각 | 2026-06-19 21:17 → 06-20 03:33 (약 6시간 16분) |
| 유효 데이터 | **F1–F10만** (100 CSV 행 = 10 fault × 5 trial × 2 system) |
| **F11/F12** | **10 trial 전량 주입 실패** (SSH 타임아웃) → CSV 행 0개 |
| 정확도 (F1–F10) | System A **41.7%** (20/48) · System B **50.0%** (24/48), **B +8.3%p** |
| Git 상태 | 전부 untracked (미커밋). plan_v10·analysis_v10 문서 없음 |

---

## 1. 이 실험이 왜 존재하는가 (배경)

### 1-1. 인프라 재구축으로 과거 데이터가 무효화됨
직전까지의 실험 환경은 **Proxmox nested 가상화** 위 K8s였고, 노드당 디스크 15G로 인한 **disk-pressure 오염**이 V8 실패의 근본 원인 중 하나였다. 이를 폐기하고:

- KT Cloud Debian 호스트 **6대에 K8s 직접 설치** (1 master + 5 worker)
- 노드 디스크 15G → **50G** (disk-pressure 근절)
- 스택: k8s v1.31.14, containerd 1.7.24, Cilium 1.19.3(kube-proxy 대체), Flux GitOps + ArgoCD, Online Boutique 12개 서비스, kube-prometheus-stack + Loki + promtail
- 재구축 PR #15 머지 완료, preflight GREEN(6/6 노드 Ready, boutique 12/12 Running) 실측

환경이 근본적으로 바뀌었으므로 **V1~V9의 trial 데이터는 새 환경의 baseline으로 무효**. 사용자 결정 = "첫 실험부터 다시" → **V10(re-baseline)**.

### 1-2. 무엇을 유지하고 무엇을 바꿨나
- **유지(불변)**: fault 정의 F1–F12, System A/B 구성, RAG, 실행 하네스, **V9 Pre-Trial State Validator**, 모델 `gpt-4o-mini`
- **변경**: trial 데이터만 새 클러스터에서 재수집. `scripts/fault_inject/config.py`의 워커 노드 접속 정보를 새 호스트(`debian@`, SSH 포트 22016~22020)로 갱신

> 즉 V10은 새 가설을 검증하는 실험이 아니라, **깨끗한 새 환경에서 측정 기준선을 다시 세우는 실험**이다. (V9의 단일 독립변수였던 State Validator는 이미 코드에 통합된 채 함께 돌아간다.)

---

## 2. 검증 대상 — System A vs System B

| | System A (베이스라인) | System B (제안 기법) |
|---|---|---|
| 입력 신호 | Prometheus 메트릭 + Loki 로그 + kubectl 상태 | A의 모든 것 **+ GitOps 컨텍스트(FluxCD/ArgoCD) + RAG 런북** |
| LLM | gpt-4o-mini | gpt-4o-mini (동일) |
| 평균 프롬프트 토큰 | 4,984 | 6,786 (+RAG/GitOps 컨텍스트만큼 증가) |

**연구 질문**: GitOps 배포 컨텍스트와 RAG 지식을 더하면 LLM의 장애 원인 분석(RCA) 정확도가 올라가는가? 모델은 고정하고 **프레임워크 레벨**에서만 개선한다.

---

## 3. 시나리오 — 12개 Fault Type × 5 trial × 2 system = 60 케이스(system별 60행)

| ID | Fault | 대상 | 주입 방식 | 카테고리 | V10 결과 |
|---|---|---|---|---|---|
| F1 | OOMKilled | cartservice 등 | 메모리 limit 축소 | service | ✅ 수집됨 |
| F2 | CrashLoopBackOff | paymentservice | startup에 exit(1) 주입 | service | ✅ (1 trial validator-skip) |
| F3 | ImagePullBackOff | frontend | 존재하지 않는 이미지 태그 | service | ✅ (1 trial validator-skip) |
| F4 | NodeNotReady | worker01 | cordon/drain + kubelet 중단 | node | ✅ 수집됨 |
| F5 | PVCPending | redis-cart | 없는 StorageClass PVC | service | ✅ |
| F6 | NetworkPolicy | frontend | deny-all ingress 적용 | service | ✅ |
| F7 | CPUThrottle | frontend | CPU limit 10m로 축소 | service | ✅ |
| F8 | ServiceEndpoint | frontend | Service selector 불일치 | service | ✅ |
| F9 | SecretConfigMap | cartservice | redis 연결 Secret 삭제 | service | ✅ |
| F10 | ResourceQuota | boutique ns | pods=5 ResourceQuota | service | ✅ |
| **F11** | **NetworkDelay** | **worker01~03** | **tc netem delay (500ms~5000ms)** | node | ❌ **주입 실패** |
| **F12** | **NetworkLoss** | **worker01~03** | **tc netem loss (10%~80%)** | node | ❌ **주입 실패** |

---

## 4. 독립 변수 — Pre-Trial State Validator (V9에서 통합, V10에도 탑재)

매 trial 주입 **직전** 클러스터 상태를 검사해 잔류 fault(stale ReplicaSet, 비정상 pod)를 자동 정정하는 모듈. SynergyRCA의 StateChecker 패턴(arxiv:2506.02490)을 K8s ReplicaSet 도메인에 단순화 적용.

**단계적 정정**: ① `kubectl rollout restart` → ② 실패 시 `delete rs --force` + restart → ③ 그래도 실패 시 trial을 **skipped**로 표시하고 통계 제외.

이 validator는 V8 실패의 근본 원인이었던 "환경 오염(이전 trial의 잔류 fault가 다음 trial 진단을 오염)"을 차단하기 위해 도입됐다.

---

## 5. 진행 경과 (타임라인)

```
06-19 21:17  F1 t1 시작 (실험 개시)
06-19 21:xx  F1~F3 진행 — F2 t4/F3 t4 validator가 잔류 fault 정정(corrected),
             F2 t5/F3 t3 정정 실패로 skipped
06-20 02:52  F10 t5 완료 ← 유효 데이터 마지막 (A/B 양쪽)
06-20 03:07  F11 t1 시작 → tc netem SSH 주입 15초 타임아웃 (전 trial 반복)
06-20 03:33  F12 t5까지 전량 주입 실패, 로그상 "60/60 complete"로 종료
```

---

## 6. 결과 — F1–F10 (유효 구간)

### 6-1. 시스템별 정확도 (validator-skip 4건 제외, 분모 48)
| | 정답/시도 | 정확도 | eval_overall 평균 |
|---|---|---|---|
| System A | 20/48 | **41.7%** | 7.92 |
| System B | 24/48 | **50.0%** | 8.04 |
| 차이 | +4 | **+8.3%p** | +0.12 |

방향은 가설(B > A)과 일치. 단, **통계적 유의성은 아직 미검정**(McNemar 등 필요).

### 6-2. Fault별 정답 수 (5 trial 중, skip 제외)
| Fault | A | B | 비고 |
|---|---|---|---|
| F1 OOMKilled | 2 | 2 | 동률 |
| F2 CrashLoop | 0/4 | 2/4 | **B 우세** |
| F3 ImagePull | 2/4 | 2/4 | 동률 |
| F4 NodeNotReady | 1 | 4 | **B 강하게 우세** |
| F5 PVCPending | 2 | 1 | A 우세 |
| F6 NetworkPolicy | 1 | 1 | 동률(둘 다 약함) |
| F7 CPUThrottle | 4 | 5 | B 우세 |
| F8 ServiceEndpoint | 1 | 1 | 동률(둘 다 약함) |
| F9 SecretConfigMap | 3 | 3 | 동률 |
| F10 ResourceQuota | 4 | 3 | A 우세 |

→ B의 이득은 주로 **F4·F2·F7**에서 발생. F6/F8은 두 시스템 모두 취약(1/5).

### 6-3. Validator 동작 통계
- `clean` 92 · `corrected` 4 · `skipped` 4 (총 100행 기준)
- **corrected**: F2 t4, F3 t4 — 양 시스템 모두 잔류 fault 정상 정정
- **skipped**: F2 t5, F3 t3 — stale findings 3건을 2회 시도로 못 고쳐 skip. **A·B 동일하게 skip**돼 비교 공정성은 유지(그래서 분모가 50 아닌 48)

### 6-4. 비용/성능
- 평균 LLM 지연 ≈ 10.4초/호출, 모델 전 행 `gpt-4o-mini` 고정 확인

---

## 7. ❗ F11/F12 주입 실패 — 원인 분석

**증상**: F11(NetworkDelay)·F12(NetworkLoss) 10 trial 전량 실패. CSV 행 0개. 로그에 동일 패턴 10회:
```
Injection failed: ssh ... -p 2201[6-8] debian@211.62.97.71
  'sudo tc qdisc add dev ens18 root netem ...' timed out after 15 seconds
```

**원인 추정**: F11/F12는 워커 노드에 SSH로 `tc netem` 룰을 거는 **SSH 기반 주입**인데, 해당 네트워크 워커 노드(`211.62.97.71:22016~22018`)로의 **SSH 연결 자체가 ConnectTimeout(10s) 내에 성립하지 못함**.

**핵심 맹점** (handoff §3-1): 재구축 직후 적응 항목에서 *"노드 접속 정보 변경은 F4(NodeNotReady)에만 영향, 나머지는 순수 kubectl이라 무관"*으로 판단했으나 — **F11/F12도 SSH 기반(tc netem)**이다. 이 fault들의 노드 접속 경로가 새 환경에서 검증되지 않은 채 캠페인이 돌았다. (F4는 데이터가 수집된 것으로 보아 F4 경로는 작동.)

**결론**: F11/F12 실패는 **모델·프레임워크 문제가 아니라 환경/접속 설정 문제**. tc netem 주입을 위한 네트워크 워커 노드 SSH 도달성(포트/방화벽/sudo)을 점검·수정 후 F11/F12만 재수집하면 됨.

---

## 8. 데이터 유효성과 한계

1. **유효 범위 = F1–F10 한정.** 네트워크 장애(F11/F12)는 V8에 이어 V10에서도 측정 불가. re-baseline은 사실상 **10/12 fault만 완료**.
2. **표본 = 48/시스템** (skip 4건 제외). 비열등성/우월성 검정의 분모로 사용 시 명시 필요.
3. **통계 미검정**: +8.3%p는 raw 수치일 뿐. McNemar χ²·신뢰구간 미산출.
4. **validator 효과 분리 불가**: V10은 validator를 끈 대조군이 없어, "환경이 깨끗해서 vs validator 덕분에"를 본 실험만으로 분리할 수 없음.
5. **미커밋**: 결과·코드·raw가 모두 git untracked. 정식 `analysis_v10.md`·`experiment_plan_v10.md` 부재.

---

## 9. 남은 작업 (제안)

| 우선순위 | 작업 |
|---|---|
| 1 | **F11/F12 SSH 주입 경로 수리** — 네트워크 워커 노드(22016~22018) 도달성·sudo·tc 확인 후 F11/F12만 재수집 |
| 2 | F1–F10으로 **정식 통계 분석**(`analysis_v10.md`) — McNemar, 시스템별/카테고리별, eval 점수 분포 |
| 3 | V10 결과·코드 **커밋 → PR**(PR-only 정책), `experiment_plan_v10.md` 사후 정식화 |
| 4 | F6/F8(둘 다 1/5) 저조 원인 진단 — 신호 부재인지 프롬프트 한계인지 |
```
