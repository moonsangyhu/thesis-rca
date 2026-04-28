# V9 실험 계획서 리뷰

**리뷰 대상**: `docs/plans/experiment_plan_v9.md`
**리뷰어**: hypothesis-reviewer agent (general-purpose subagent)
**리뷰 일시**: 2026-04-28
**결론**: **조건부 승인**

---

## 후속 (Follow-Up) — 2026-04-28

`experiment_plan_v9.md` 1차 리비전에서 §7 **필수 수정 5건이 모두 반영**되었다. 권장 수정 #10(경계 시나리오)도 §10-3에 promoted. 권장 수정 #6~#9, #11, #12는 V9 분석 리포트(`results/analysis_v9.md`) 또는 sensitivity analysis로 사후 처리.

| 필수 수정 | 반영 위치 |
|---|---|
| #1 F11/F12 node 카테고리 책임 분리 | §0-2 (validator는 deployment 레벨만, 노드 레벨은 recovery.py. 직전 F11/F12 trial=5인 경우 cooldown 1500s + tc qdisc 사전 점검) |
| #2 `_is_abnormal()` restartCount 임계값 상향 | §3-1 코드 스케치 (≥10 + baseline 대비 +5 carry-over 검사) |
| #3 `_wait_stable` rollout-based 변경 | §3-1 코드 스케치 (`kubectl rollout status` timeout=120s, deployments set 인자) |
| #4 `--resume` skipped 처리 정책 | §0-3 (`--retry-skipped` 플래그, max 1회 재시도, `skipped_permanent` 영구 고정) |
| #5 F11+F12 skipped 임계값 | §10-3 실패 판정 (skipped > 4/10 → 가설 검증 불가) + 경계 시나리오 [1/10, 3/10] |

본 후속 노트는 리비전 추적 목적이며, 본 리뷰의 결론(조건부 승인)은 위 반영으로 해소된 것으로 간주한다. 추가 검증은 V9 dry-run 결과로 대체.

---

## 0. 사전 메모 — Auto Mode 가정에 대한 평가

본 plan은 Auto Mode + 백그라운드 호출 환경에서 작성되어 사용자 질문 단계가 생략되었으며, brainstorming 5축 답변이 §0에 자가-답변 형태로 명시되어 있다. 본 리뷰는 §0의 5개 가정 각각이 V8 데이터·문헌·코드 변경 가능성에 비추어 합리적인지 검증한다. 결과적으로 §0-1, §0-3, §0-5는 합리적이며, §0-2(target_service 화이트리스트)와 §0-4(RAG chunk header를 환경 전제조건으로 분류)는 조건부 합리성 — 후술 §2.3·§2.1에서 보강 필요사항을 지적한다. Auto Mode 가정 자체를 재설계할 필요는 없다.

---

## 1. 이전 결과 분석 평가

### 충분한 부분

- **McNemar 비유의 결론(§1-1, §2)이 정확하다**. V9 plan은 V8 plan §10에서 "회귀"로 판정한 결과를 평균 점수(score) 기준이지 binary(≥0.5) 기준의 차이가 아니라고 재해석했으며(`deep_analysis_v9.md` §1-1과 일치), 이는 V8 raw 데이터에 기반한 보다 보수적인 해석이다. McNemar χ² = 0.40, p ≈ 0.53의 인용은 정확하다.
- **잔류 RS 발견의 데이터 근거가 충분히 제시되었다**(§1-1 발견 + §2-4 raw_v8 실측). `shippingservice-865585fdff` RS, restart count 26→32→36→38 누적, 정상 RS `759b59d959`와 공존이라는 메커니즘 기술은 raw_v8 샘플(F11 t1, t5, F12 t1, t3)에 부합한다(`deep_analysis_v9.md` §1-2와 일치).
- **METRIC ANOMALIES 중복 가설을 raw_v8 120 파일 grep으로 직접 기각**(§0-4, §2-4)하고 RAG chunk header 중복으로 정정한 것은 데이터 기반 의사결정이며, deep_analysis_v9에서 잠정 결론으로 남겨두었던 가설 c를 코드 단계 진입 전에 보완한 점이 모범적이다.

### 놓친 패턴 및 부족한 부분

- **F2 score 분포 shift(V7 100% → V8 30% avg)에 대한 본질 분석이 미해소**. §2-3-2에서 이 효과를 "V9에서 carry-over"로 인정하면서도 V9 plan 안에 보정 메커니즘이 없다. F2가 V9에서도 부분 점수에 머물 경우, 이것이 (가) validator 미작동(잔류 RS 정정 실패) 때문인지 (나) judge 본질 변화(컨텍스트 길이 + specificity) 때문인지 사후 분리 불가하다. 권고: §11에 리스크 7로 추가하고, F2 raw_v9에서 "정정 후 잔류 RS 0건" 검증 후에도 부분 점수가 발생하면 (나)로 귀착하는 결론 규칙을 사전 정의해야 한다.
- **System A의 F11/F12 정확도 변화 추적이 V9 plan에 부재**. V8 plan §1-2-1 근거 2의 "ΔA<sub>F11/F12</sub> ≈ 메트릭 단독 효과 / Δ(B−A) ≈ RAG/런북 효과" 분해는 validator가 A/B 모두에 동일 적용되는 V9에서도 유효하다. V9 §12-3에서 "validator는 A/B 모두에 동일 적용되므로 효과 직교"라고만 언급하고 분해 보고가 빠져 있다. 권고: §12에 "ΔA<sub>F11/F12</sub>(V8→V9) ≈ validator 단독 효과 (A는 RAG 미사용)"의 분해 항목 추가.
- **F1-F10 binary 회귀의 출처가 V9 §2-2 표에 산입되지 않았다**. V9 plan은 V8 B의 binary 점수를 (F1=1/5, F2=0/5, F3=4/5, ...) 등으로 표시하지만, V8 analysis_v8 §1-1에 따르면 F1-F10 ≥0.5 cutoff = 21/50(42%)로 V7의 23/50(46%) 대비 -4pp이다. 이 binary 회귀는 §1-1에서 "McNemar p ≈ 0.53로 통계적 동등"으로 처리되었지만, 본질적으로는 6 lost vs 4 gained의 paired 변동이다. V9 §10-1 주 기준 2 "F1-F10 B (≥0.5) ≥ 21/(50 − skipped_count)"는 V8 baseline을 그대로 승계하는데, V7=23 대비로는 추가 회귀 위험이 있다. 권고: 주 기준 2의 baseline을 21(V8) 대신 V7=23 또는 V7-2pp=21 중 무엇으로 잡는지 명확히 하고, 후속 분석에서 V7 대비 누적 회귀 추적도 같이 보고.

---

## 2. 핵심 가설 검토

### 2.1 단일 변수 정당화 — RAG chunk header 중복 제거의 분류 (중간)

§1-2-1 근거 1~4는 V8 plan §1-2-1과 같은 톤으로 잘 작성되어 있으며, 특히 SynergyRCA StateChecker 인용(근거 4, arxiv:2506.02490 precision ≈ 0.90)은 V9 가설의 문헌적 정당화로 적절하다. 그러나 한 가지 분류 문제가 남아 있다.

**핵심 비판**: §0-4는 RAG chunk header 중복 제거를 "환경 전제조건(독립변수 아님)"으로 분류했지만, 이는 RAG retrieval/format 단의 코드 변경이다. 진정한 의미의 "환경 전제조건"은 클러스터·데이터·인프라 상태(예: lab-restore, RAG 재인덱싱)이며, **코드 변경은 본질적으로 독립변수 후보**다.

§1-2-1 근거 3에서 "header 중복 제거의 효과 ≈ 컨텍스트 토큰 감소(~5-15 tokens/trial)"로 작은 효과만 예상하지만, 이 효과 자체는 **측정될 수 있고**, 측정되지 않으면 V9 결과가 (가) validator 효과인지 (나) header 정제 효과인지 부분적으로 혼재한다. V8 plan §1-2-1 근거 1의 "기술적 선행조건 관계로 분리 불가"가 V9의 두 변경에는 적용되지 않는다 — header 중복 제거는 validator와 기술적으로 독립이며, 따로 적용해도 동작한다.

**권고**:
1. 명목상 "환경 전제조건" 분류를 유지하되, §1-2-1 근거 3의 한계(상호작용 미측정)를 §13 분석 §11(리스크)에 명시적으로 추가하여 V9 결과 해석 시 "header 효과 ≤ 토큰 5-15개 감소"라는 상한을 적용한다고 사전 등록한다.
2. 또는 더 강한 대안: V9에서는 header 중복 제거를 보류하고 V10에서 별도 변수로 다룬다(이 경우 §0-4 가정 변경, dry-run에서 header 중복은 그대로 남게 되며 해석 시 baseline으로 처리). 이는 단일 변수 원칙에 더 엄격하지만 V9 timeline에 +1일 영향. 1 또는 2 중 사용자 선택.

### 2.2 Stale 판정 알고리즘 (§0-1) — RS-level + Pod-level 합집합의 false positive (중간)

`replicas.status.replicas >= 1` AND `RS != latest RS` (RS-level) **OR** `target_service가 아닌 boutique pod가 abnormal` (Pod-level) 합집합 검사는 잔류 fault 검출 recall을 높이지만 false positive 위험이 있다.

**구체 시나리오**:
- (가) **legitimate 노이즈 pod**: `kube-prometheus-stack`이 만들어내는 임시 metrics-server pod, evicted pod 정리 지연 등은 boutique 네임스페이스 내가 아니지만, 만약 boutique 네임스페이스에 다른 워크로드(예: helm test pod)가 잠시 들어오면 `target_service`가 아니므로 stale로 분류됨.
- (나) **transient pod restart**: F1(OOMKilled) trial이 끝난 직후 다음 F2 trial 진입 시 OOM된 pod의 잔류 restart count ≥ 5가 발견되면 Pod-level 검사가 stale로 잡고 정정을 시도. 그러나 이는 직전 fault의 의도된 결과 흔적이지 V7→V8 같은 cross-version 잔류물이 아님.
- (다) **Pod-level abnormal 정의의 확장 위험**: §3-1 `_is_abnormal()`이 "restartCount ≥ 5"를 abnormal로 분류. 정상적 cluster restart 후 일부 pod의 restartCount가 5+에서 stable하게 동작하는 경우(예: liveness probe 초기 실패 후 안정화)도 stale로 오분류.

**대응의 미흡 부분**: §3-1의 화이트리스트는 "현재 fault의 target_service"만 보호하고, "직전 fault의 잔류"와 "환경 노이즈"를 구분하지 않는다. recovery.py가 trial 종료 시 pod restart count를 reset하지 않으므로(현재 코드 미검토 가정) 직전 fault 효과가 다음 trial validator에서 stale로 잡혀 불필요한 정정이 누적될 수 있다.

**권고**:
1. `_is_abnormal()`의 "restartCount ≥ 5" 임계값을 trial 시작 시점 기준 **상대 증가량**으로 재정의하거나(예: 직전 trial 종료 시점 대비 +5), 또는 절대 임계값을 ≥ 10으로 상향. 5는 RUM/일반 운영 베이스라인에서 자주 나오는 값.
2. dry-run §7-2-2의 stale RS 인위 생성 시나리오 외에 **"직전 fault 정상 종료 후 다음 trial 진입"** 케이스(예: F1_t5 → F2_t1)에 validator 출력이 `clean`인지 검증하는 항목을 §7-2-3 통과 기준에 추가.
3. 이상이 발견되면 false positive 비율을 trial별로 raw에 기록하여 §12-5 effectiveness 분석에서 검토.

### 2.3 단일 변수 식별 (§0-2) — `target_service` 화이트리스트의 정확성 (중간)

`FAULT_TARGET_TYPE` 매핑(§3-1)에서 F1-F3, F5-F10은 "service" 카테고리로 묶여 ground_truth `target_service` 컬럼의 deployment를 화이트리스트로 사용한다. F4, F11, F12는 "node" 카테고리로 모든 boutique deployment의 abnormal pod를 stale로 본다.

**핵심 비판**:
- (가) **F11/F12에서 fault inject가 의도적으로 boutique pod 신호를 변화시킬 수 있다**. tc netem delay/loss로 인해 worker 노드의 모든 service가 latency/error를 보이고, 일부는 readiness probe 실패로 NOT READY 상태에 진입. V9 plan §0-2는 "node 카테고리에서는 모든 abnormal pod = stale"이라고 결정했는데, 이는 fault inject의 의도된 결과(예: F11 5000ms delay 시 frontend가 backend 호출에 실패하여 일시적 NOT READY)도 stale로 분류해 정정을 시도하게 만든다. 정정은 fault inject 자체를 무력화한다.
- (나) **F11/F12 화이트리스트 부재의 의도와 실제 효과 차이**. V9 plan은 F11/F12를 "node" 카테고리로 둔 이유를 §3-1 코드 주석에서만 설명("worker01-03"). 그러나 fault 의도는 "특정 worker 노드의 네트워크 장애"이지 "노드 자체의 정지"가 아니다. F11/F12의 트리거 시점은 inject **이후**이고 validator는 inject **이전**(Step 0.5)에 실행되므로 timing상 fault 의도된 결과를 stale로 오인할 가능성은 낮지만, **이전 trial의 F11/F12 잔류**(tc netem 미해제, 노드 NotReady 잔류)는 다음 trial에서 모든 boutique deployment의 abnormal로 검출될 수 있다. 이 경우 validator는 잔류 정정을 시도하지만 tc netem 자체는 `kubectl rollout restart`로 해제되지 않으므로 무한 루프 또는 attempts=2 후 skipped 발생.

**대응의 미흡 부분**: §3-1 `_correct()`는 deployment rollout과 RS force delete만 수행하고, **노드 레벨 fault(tc netem, NodeNotReady) 정정은 다루지 않는다**. recovery.py가 fault별로 처리하던 부분이 validator로 이전되지 않았다.

**권고**:
1. F11/F12에 대해서는 validator의 정정 범위를 "이전 fault가 application service에 미친 잔류 영향(stale RS)"로 한정하고, **노드 레벨 잔류(tc netem, NotReady)는 recovery.py의 fault별 cleanup이 처리한다는 책임 분리를 §3-1 docstring과 §11 리스크에 명시**.
2. F11/F12 직전 trial의 cleanup 검증을 §7-1 사전 점검 또는 §7-2-2에 추가: `tc qdisc show dev <iface>`로 worker01-03에 잔류 netem 룰이 없는지 확인. 잔류 시 validator가 아닌 별도 cleanup 트리거.
3. `target_service` 컬럼에 변경/오타가 있을 경우 화이트리스트가 무력화되므로, validator 시작 시 ground_truth.csv 모든 행의 target_service가 실제 deployment 명단(`kubectl get deploy -n boutique -o name`)에 매칭되는지 사전 검증하는 단계를 §6 검증 체크리스트에 추가.

---

## 3. 교란 변수 검토

### 3.1 Validator 자체가 trial 결과에 영향 (중간)

`rollout restart deploy/<name> + 60s 대기`(§0-3, §3-1) 액션은 다음과 같은 부수효과를 만든다:

- **컨텍스트 신호 분포 변경**: rollout restart는 새 ReplicaSet과 새 pod를 만들고, 새 pod는 starting 상태에서 일정 시간 후 Ready로 전환. validator wait 60s가 Ready 도달을 보장하지 못하면, trial 시작 직후 컨텍스트에 starting/Pending pod가 등장. LLM이 이를 fault로 오인할 위험.
- **메트릭 시계열 단절**: rollout restart로 pod가 교체되면 Prometheus 시계열이 재시작되며, 직전 5분 윈도우의 baseline metric이 "no data"가 되거나 새 series로 교체. F11/F12 직전 trial의 baseline 메트릭이 V8과 V9에서 다른 양상이 됨.
- **GitOps 컨텍스트 변경**: FluxCD/ArgoCD가 manifest와의 drift를 감지할 수 있으며 (rollout restart는 spec.template 어노테이션에 timestamp 추가), V8과 V9의 GitOps 섹션 출력 미세 차이 발생.

V9 plan §11 리스크 6에서 "validator overhead가 inject 시점 정렬 영향 무시 가능"으로 처리했으나, 위의 신호 분포 변경 효과는 별개 이슈다.

**권고**:
1. validator wait를 60s에서 **rollout completion 확인**(예: `kubectl rollout status deploy/<name> --timeout=120s`) 기반으로 변경. 단순 `time.sleep(60)`은 rollout 미완료 위험.
2. validator 호출이 발생한 trial과 발생하지 않은 trial을 paired로 비교하는 sub-analysis를 §12-5 또는 §12-6에 추가하여 validator 부수효과를 측정.
3. 만약 corrected trial과 clean trial의 LLM 정답률에 통계적으로 유의한 차이가 있다면, 이는 validator가 fault 진단 자체에 영향을 주는 신호이므로 §13 시나리오 D를 강화하여 "corrected trial의 정답률이 clean trial 대비 -10pp 이상 낮으면 V9 결과를 clean trial subset으로 재계산"하는 fallback 분석 규칙 추가.

### 3.2 skipped trial이 통계 분모를 변동시키는 효과 (중간)

§0-5와 §10-1 주 기준 2의 분모 = 50 − skipped_count는 비열등성 검정의 분모 변동을 일으킨다.

**핵심 비판**:
- skipped trial이 "validator가 정정 실패한 trial"이지 "랜덤 누락"이 아니다. 즉 fault별 skipped 분포는 비랜덤이며, 특정 fault에 skipped가 집중되면 baseline 비교가 distorted됨.
- V8 plan §12-4 비열등성 검정 δ=-5pp는 **n=50 가정**으로 설계되었다. n이 줄어들면 95% CI 폭이 넓어지고 비열등성 입증이 어려워짐. 예: skipped=4, n=46이면 23/46 vs V7 23/50 비교에서 CI 폭이 ±15.5pp → -5pp 한계 초과 가능성 증가.
- §10-3 실패 판정 "skipped > 12/60"은 절대 임계값이지만, fault별 분포 균형은 다루지 않음. F11/F12 5건 모두 skipped면 핵심 가설 검증 자체가 불가능하면서도 절대 임계값(12)에는 미달.

**권고**:
1. §10-3에 "F11+F12 skipped > 4/10"을 추가 실패 판정으로 둔다(F11/F12 필수 검증력 확보).
2. §12-4 비열등성 검정에서 skipped > 0인 경우 분모 보정 외에 **paired 검정으로 보완**하기로 §0-5에 명시했으나 구체 절차는 미정. 권고 절차: V7과 V8 모두 정상 결과가 있는 (fault, trial) 쌍에 대해서만 V9 결과를 비교하고, V7/V8/V9 모두 정상인 trial subset에 대해 별도 sub-analysis 보고.
3. skipped trial은 §3-2 `_record_skipped()`로 raw에 metadata만 저장된다고 명시되었는데, **재시도 정책**(§7-4 `--resume`)이 skipped trial을 다시 실행하는지가 불명확. resume 시 validator가 또 skipped 처리하면 무한 루프. resume 시 skipped trial은 max 1회 재시도하고 그래도 실패하면 영구 skipped로 고정하는 규칙 명시 필요.

### 3.3 RAG chunk header 중복 제거가 retrieval 품질에 미치는 미세 효과 (낮음-중간)

§3-5 변경 위치가 "ingest 또는 retriever format"로 미정이며 code 단계에서 결정된다고 명시. 변경 위치에 따라 효과가 달라질 수 있다.

- **ingest 단**: chunk text 자체가 변경되면 ChromaDB 임베딩이 재계산되며, F2/F11/F12 검색 top-k 순위가 V8과 미세하게 달라질 수 있음. §7-1 통과 기준 "F2 top-3 source가 V8과 동일"이 임베딩 변동으로 깨질 수 있다.
- **retriever format 단**: 임베딩은 그대로이고 출력만 정제되므로 검색 품질 영향 거의 없음. 이 경로가 더 안전.

**권고**:
1. 코드 단계(@code-reviewer)에서 retriever format 단을 **우선 후보**로 채택하고, ingest 단 변경은 회피. 만약 ingest 단을 변경할 수밖에 없다면 §7-1 통과 기준 "F2 top-3 source 동일" 확인 후 차이 발생 시 §11 리스크 5 대응대로 V10으로 이월.
2. §3-5 본문에 위 우선순위 규칙 명시.

---

## 4. Ground Truth 적정성

### 4.1 V8 §10-0 (a) tc netem K8s 포트 제외의 V9 승계 (적절)

§10-0에서 V8 plan §10-0의 (a)/(b)/(c)를 그대로 승계한다고 명시. tc netem이 6443/10250/2379/2380 포트를 제외한다는 결정은 V8에서 검증되었으며(`scripts/fault_inject/network.py` 가정 — code 단계에서 미변경), V9에서 fault injection 코드는 변경되지 않으므로 일관성이 유지된다.

다만 review_v8 §3.1에서 지적한 "tc netem K8s 포트 제외가 application-level 신호를 너무 약화"가 V8 결과에서 실제로 확인되었다(`analysis_v8.md` §4: "node-exporter 메트릭은 interface 레벨 신호로 application 레벨 fault와 직접 매핑되지 않음"). V9는 이 한계를 시나리오 Beta carry-over로 받아들이고 application-level 메트릭(gRPC) 추가는 V10으로 보류한다(§15 우선순위 1). 이는 단일 변수 원칙에 충실한 결정이며 적절하다.

### 4.2 §10-0-(d) Validator 개입 시 판정 규칙의 (b) 5×5 테이블과의 상호작용 (적절, 단 보강 필요)

§10-0-(d)는 validator의 corrected/skipped 상태별 판정을 추가했고, V8 §10-0-(b)의 NodeNotReady 부작용 5×5 테이블과 직교적으로 작동한다(validator는 trial 시작 전, NodeNotReady 판정은 trial 종료 후 LLM 진단).

**보강 필요사항**: F11_t5(5000ms delay), F12_t5(80% loss) 같은 고위험 trial에서 **validator가 직전 trial의 NodeNotReady 잔류를 stale로 분류**할 수 있다. §0-2에 따르면 F11/F12는 "node" 카테고리이므로 validator는 노드 비정상을 보고하지만, 실제 정정은 deployment rollout과 RS force delete뿐이며 노드 NotReady는 정정 불가 → skipped 처리. 이 시나리오에서 직전 trial의 V8 §10-0-(b) "NodeNotReady 부작용"이 다음 trial의 validator skipped로 이어지는 cascade 효과 발생.

**권고**:
1. §10-0-(d)에 "validator가 노드 NotReady를 stale로 검출한 경우" 행 추가: 이 경우 정정 시도 전에 노드 상태 확인하고, NotReady가 직전 fault의 기대 부작용이면(직전 trial = F11_t5 등) skipped가 아닌 **별도 통계 카테고리(node-recovery-pending)**로 처리. trial 자체는 skipped와 동일하게 통계 제외하지만 §10-3 실패 판정에서는 별도 카운트.
2. 또는 더 단순하게: 직전 trial이 F11/F12 고위험 trial인 경우 cooldown을 900s에서 1500s로 일시 상향(F4 노드 정상화 시간 확보). §5 실험 파라미터에 추가.

---

## 5. 통계 검정 방법 검토

### 5.1 Validator effectiveness 측정 (§12-5) — 측정 정의의 명확성 부족 (중간)

§12-5는 stale RS 검출 precision/recall, 정정 성공률, skipped 분포를 측정한다고 명시했으나 **operational 정의**가 모호.

- **Precision**: "validator가 stale로 분류한 RS 중 실제 잔류 fault 비율" — "실제 잔류 fault"의 ground truth 정의가 없음. raw_v9에서 인공 검증한다고 했으나 검증 기준이 명시되지 않음. 권고: "이전 trial의 fault inject로 인한 RS이거나 V8 이전 잔류"라는 조건을 명시하고, raw_v9 메타데이터에서 직전 trial fault_id와 RS owner를 매칭하는 자동화 가능.
- **Recall**: "V9 trial 시작 시점에 존재한 실제 잔류 RS 중 validator가 검출한 비율" — V9 본 실험에서는 의도적 stale 주입 없이 자연 발생 stale만 측정한다고 §12-5에서 명시했으나, 자연 발생 stale의 ground truth 자체가 없으므로 recall 계산 불가. 본 V9에서는 precision만 측정 가능하고 recall은 V10으로 이월한다고 §12-5에 명시되어 있어 적절. 다만 이 한계는 §13 시나리오 A "잔류 RS는 깨끗한데도 진단 실패" 판정 시 recall 미측정으로 인해 "잔류 RS가 정말 깨끗한지" 검증이 어렵다는 점에서 약점.
- **정정 성공률**: "corrected 후 재scan에서 findings=0 비율" — `_scan()`이 동일 알고리즘이므로 trivially 100%(`_correct` 후 즉시 재scan, attempts<2 일 때) 또는 0%(attempts=2 후도 stale → skipped). 의미 있는 metric이 아님. 권고: "corrected 직후 + 60s 대기 후" 재scan에서도 findings=0인 비율 또는 "corrected trial의 LLM 정답률 / clean trial의 LLM 정답률"을 effectiveness proxy로 추가.

**권고**: §12-5의 3개 metric에 대해 위 operational 정의를 plan 본문에 명시. raw 데이터 기반 자동 계산 가능 여부도 함께 기재.

### 5.2 skipped trial의 paired 검정 처리 (중간)

§12-1 주 검정 (V9 B vs V8 B McNemar)에서 "skipped trial은 분모에서 제외"한다. 그러나 paired 검정에서 skipped trial을 어떻게 다룰지 규칙이 불완전.

- **케이스 1**: V8 정상 + V9 skipped → V8의 정답/오답 정보가 paired 비교에서 손실. 이 trial을 b/c/d 어디에도 산입하지 않으면 검정력 저하.
- **케이스 2**: V7 정상 + V8 정상 + V9 skipped → V7-V8 paired, V8-V9 paired 모두 영향.

V8 §12-4 비열등성 검정의 분모 보정(50 − skipped_count)은 산술적이지만, McNemar 검정은 paired 가정 위반.

**권고**:
1. §12-1에 "skipped trial은 (fault, trial) 쌍에서 V8/V9 양쪽 모두 정상인 경우만 paired 비교 대상"으로 명시.
2. skipped trial이 5건 이상이면 sensitivity analysis로 "skipped trial을 모두 V9 오답으로 가정한 보수적 추정치"와 "모두 V9 정답으로 가정한 낙관적 추정치"를 함께 보고하는 절차 추가.

### 5.3 비열등성 검정 δ=-5pp 승계 + skipped 보정 (적절)

§12-4는 V8 §12-4 비열등성 검정 δ=-5pp 사전 등록을 그대로 승계하고 분모만 50 − skipped_count로 보정. 이는 V8 plan critique에서도 명시된 "사전 등록 후 변경 불가" 원칙에 충실하다.

다만 위 §5.2에서 지적한 분모 보정의 검정력 저하 문제는 V9 결과 해석 시 다시 제기될 수 있으므로, §12-4에 분모 = 50 − skipped_count가 30 이하로 떨어지면 비열등성 검정 자체를 보류하고 sensitivity analysis로 대체한다는 fallback 규칙 추가 권고.

---

## 6. 대안 가설 검토

### 6.1 F11/F12 ground truth 자체의 모호함이 진짜 한계 (가능성 중)

deep_analysis_v9 §3-2와 analysis_v8 §4는 "node-exporter 메트릭이 application 레벨 fault와 직접 매핑되지 않음"을 보고했다. V9가 환경 오염을 제거해도 다음 시나리오가 가능:

- 컨텍스트에 잔류 RS가 없어진 상태에서 LLM이 보는 신호 = pod_status (모두 Running), node_status (모두 Ready), metric_anomalies (대부분 빈 결과), GitOps (네트워크와 무관)
- 이 상태에서 LLM은 "특별한 이상 없음"으로 판단하거나 "노이즈 신호 중 가장 강한 것"(예: cilium drop, etcd grpc canceled)을 root cause로 보고할 가능성이 높음
- 즉 잔류 RS 제거가 F11/F12 정답률 0% → 0% 또는 0% → 5%만 만들고 40% 도달 실패 가능

V9 plan §13 시나리오 A는 이 가능성을 인지했고 V10에서 가설 b(gRPC instrumentation)로 이동을 명시. 적절한 대응이지만, V9가 이 시나리오에 빠질 확률을 deep_analysis_v9 §6-1과 analysis_v8 §4에 비추어 보면 **30-50%**로 결코 낮지 않다. §10-3 실패 판정 "F11+F12 < 1/10"은 매우 낮은 임계값이고, V9가 1/10~3/10에 도달하면 §10-1 주 기준 1(≥4/10) 미달이지만 §10-3 실패 판정은 비발동 → 결과 해석이 회색 지대.

**권고**: §10-3에 "F11+F12 합산 ∈ [1/10, 3/10]" 경계 시나리오 추가. 이 경우 잔류 RS 정정은 작동했으나 application 메트릭 부재가 fundamental 한계임을 결론지을 수 있는 근거(예: corrected trial subset에서도 정답률 동일)를 §13에 사전 정의.

### 6.2 tc netem K8s 포트 제외가 application-level 신호를 너무 약화 (가능성 중-높)

V8 plan §10-0-(a) "현실성에 대한 한계 명시"가 V9에서도 그대로 carry-over. analysis_v8 §4에서 "tc netem K8s 포트 제외 + interface 레벨 적용이라 노드 카운터에는 거의 잡히지 않을 가능성"이 실제로 Beta 결과를 설명. V9 validator는 잔류 RS만 정정하지 tc netem 신호 강화는 다루지 않으므로, **이 한계는 V9에서 그대로**.

만약 이 가설이 fundamental cause라면, V9는 잔류 RS 제거 효과만 보고 F11/F12에서 "no signal" 컨텍스트를 만들어 LLM이 "환경 정상" 또는 "noise-driven" 진단을 하게 됨.

**권고**: §13 시나리오 A에 이 대안 가설을 명시 추가. V9 raw에서 잔류 RS 정정 후의 F11/F12 컨텍스트 metric_anomalies가 "No anomalies detected"로 출력되는 비율이 80% 이상이면 application 신호 부재가 진짜 한계임을 결론.

### 6.3 gRPC 메트릭 부재가 더 큰 limit (V10 가설 b, deep_analysis_v9 §8 보류 사유)

V10 가설 b로 이미 보류됨(§15 우선순위 1, §8 §13 시나리오 A 모두 일관). 적절. V9 결과가 이 가설을 검증하는 단계라는 점이 §13에서 명확하므로 추가 권고 없음.

### 6.4 F2 score 분포 shift는 judge 본질 변화 (가능성 중)

deep_analysis_v9 §1-5와 analysis_v8 §3-2에서 F2가 V7 100% → V8 30%(avg, full=0/partial=3)로 폭락한 원인을 "컨텍스트 길이 + root_cause specificity 저하"로 추정. V9는 컨텍스트 길이를 V8과 동일하게 유지하므로(메트릭 4종 carry-over) 이 효과는 carry-over.

만약 F2 V9 결과가 V8 30%(avg) 수준에 머물면, 이는 (가) validator가 의도된 CrashLoop을 stale로 오인하지 않아 정상 작동하면서도 (나) judge 본질 변화가 fundamental cause임을 의미. V9 plan §13 시나리오 B는 F1-F10 전체 회귀만 다루고 F2 단일 fault score 분포 문제는 미해소.

**권고**: §11에 리스크 7 추가 — "F2 carry-over 부분 점수 문제: V9 plan은 F2 점수 회복 메커니즘이 없으므로 V8 30% 수준 유지 시 V10에서 judge prompt 보강 또는 root_cause specificity 강화 plan으로 이행한다"고 사전 명시.

---

## 7. 수정 사항 목록

### 필수 수정 (실험 전 반영)

1. **F11/F12 화이트리스트 정책 명시 (§2.3)**: §3-1 또는 §0-2에 F11/F12 "node" 카테고리에서 validator가 노드 레벨 잔류(tc netem, NotReady)는 정정하지 않고 recovery.py 책임이라는 분리 원칙을 명시. 직전 trial이 F11/F12 고위험 trial인 경우 cooldown 일시 상향(900s → 1500s) 또는 사전 점검에서 `tc qdisc show`로 노드 잔류 검증.

2. **`_is_abnormal()` restartCount 임계값 재정의 (§2.2)**: §3-1 코드 스케치의 "restartCount ≥ 5"를 ≥ 10으로 상향하거나 trial 시작 시점 baseline 대비 상대 증가량으로 변경. dry-run §7-2-2에 "F1_t5 직후 F2_t1 진입 시 validator clean 검증" 항목 추가.

3. **validator wait를 rollout completion 기반으로 변경 (§3.1)**: §3-1 `_wait_stable(60)`을 `kubectl rollout status deploy/<name> --timeout=120s`로 대체. 단순 sleep은 rollout 미완료 위험.

4. **skipped trial 재시도 규칙 명시 (§3.2)**: §7-4 `--resume` 동작 시 skipped trial 처리 정책(max 1회 재시도, 영구 skipped 고정)을 §0-3 또는 §3-2에 추가. 무한 루프 방지.

5. **F11+F12 skipped 임계값 추가 (§3.2)**: §10-3 실패 판정에 "F11+F12 skipped > 4/10" 추가. 핵심 가설 검증력 확보.

### 권장 수정 (가능하면 반영)

6. **RAG chunk header 변경 위치 우선순위 (§3.3)**: §3-5에 "retriever format 단 우선, ingest 단 변경 회피" 규칙 명시. ingest 단 변경 시 §7-1 RAG 일관성 검증의 fallback(V10 이월) 절차 강화.

7. **§12-5 Validator effectiveness 정의 명확화 (§5.1)**: precision/recall/정정 성공률의 operational 정의를 plan 본문에 명시. 특히 "정정 성공률"은 "corrected 직후 + 60s 대기 후 findings=0 비율" 또는 "corrected trial의 LLM 정답률 / clean trial 정답률" proxy로 변경.

8. **System A 분해 보고 (§1)**: §12에 "ΔA<sub>F11/F12</sub>(V8→V9) ≈ validator 단독 효과 (A는 RAG 미사용)" 분해 항목 추가. V8 plan §1-2-1 근거 2와 일관성.

9. **F2 carry-over 리스크 명시 (§6.4)**: §11 리스크 7로 추가. V9에서 F2 30% 유지 시 V10에서 judge/root_cause 강화 plan 이행 방향 사전 등록.

10. **경계 시나리오 (§6.1)**: §10-3 또는 §13에 "F11+F12 ∈ [1/10, 3/10]" 경계 시나리오 추가. 잔류 RS 정정 작동 vs application 메트릭 부재 한계 분리 결론 규칙.

11. **paired 검정 skipped 처리 명시 (§5.2)**: §12-1에 "skipped trial은 (fault, trial) 쌍에서 V8/V9 양쪽 모두 정상인 경우만 paired 비교 대상" 명시. sensitivity analysis(skipped → V9 오답/정답 가정 양극단)도 5건 이상 시 의무화.

12. **F1-F10 baseline 명확화 (§1)**: §10-1 주 기준 2의 baseline = V8 21 vs V7 23 중 어느 것을 비열등성 비교 대상으로 삼는지 §12-4에 명시. V7 누적 회귀 추적도 분석 §11(리스크)에 포함.

---

## 8. 종합 판정

**조건부 승인**

V9의 핵심 가설("환경 오염(잔류 RS) 제거가 V8 F11/F12 실패의 dominant cause")은 V8 raw_v8 100% F11/F12 trial에서 잔류 RS `shippingservice-865585fdff` 발견이라는 **결정적 데이터 증거**에 기반하고 있으며, SynergyRCA StateChecker(arxiv:2506.02490) 문헌 인용으로 측정 인프라(measurement infrastructure) 변경의 정당화도 충분하다. McNemar 비유의 결론 도출, RAG chunk header 중복 발견(METRIC ANOMALIES 가설을 raw 120 파일 grep으로 직접 기각), V8 §10-0 판정 규칙 승계 등 plan 품질은 V8 plan 1차 리비전 대비 향상되었다.

다만 다음 5가지 방법론적 약점이 본 실험 진행 전 보강되어야 한다:

1. **F11/F12 "node" 카테고리에서 validator의 책임 범위가 불명확하다** — 노드 레벨 잔류(tc netem, NotReady)를 deployment rollout으로 정정하려는 시도는 실패하고 skipped 누적을 야기한다. recovery.py와의 책임 분리 원칙 명시 필요(§7 필수 수정 1).

2. **`_is_abnormal()` restartCount 임계값 ≥ 5는 false positive 위험이 있다** — 정상 운영 baseline에서 자주 발생하는 값으로, 직전 fault의 의도된 결과가 다음 trial validator에 stale로 검출되어 불필요한 정정 누적 가능(§7 필수 수정 2).

3. **`_wait_stable(60)` 단순 sleep이 rollout 완료를 보장하지 못한다** — trial 시작 시 starting/Pending pod가 컨텍스트에 등장하여 LLM이 fault로 오인할 위험(§7 필수 수정 3).

4. **`--resume` 시 skipped trial 처리 정책이 미정** — 무한 루프 방지를 위해 max 재시도 + 영구 고정 규칙 명시 필요(§7 필수 수정 4).

5. **§10-3 실패 판정에 F11/F12 subset skipped 임계값 부재** — 핵심 가설 검증력 보장을 위해 "F11+F12 skipped > 4/10" 임계값 추가 필요(§7 필수 수정 5).

위 필수 수정 5건을 §3-1 코드 스케치 보강 + §7-2-2 dry-run 항목 추가 + §10-3 실패 판정 표 갱신으로 반영한 후 본 실험 진행을 권고한다. 권장 수정 7건은 분석 리포트(§13 또는 results/analysis_v9.md)에 사후 명시로도 처리 가능. **본 V9 plan은 필수 수정 5건 반영 시 실험 진행 가능한 수준**이며, V8 plan 1차 리비전 사례와 동일하게 1차 리비전 후 review_v9 후속(Follow-Up) 노트로 마무리하는 절차를 권고한다.

작성: 2026-04-28 (KST)
