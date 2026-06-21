# V2.2 실험 결과 비판적 분석 (독립 분석가)

> 작성: 2026-06-22 · 분석 대상: results/experiment_results_v2_2.csv (300행) + results/raw_v2_2/*.json (300개)
> 입장: 이 실험을 수행한 오케스트레이터와 분리된 fresh 시각. "RAG/B가 효과 있다"는 확증 편향을 경계하고 결함·교란·한계를 능동 탐색했다.
> 모든 수치는 본 분석가가 `.venv/bin/python`(numpy/scipy, statsmodels 부재 확인됨)으로 직접 계산한 결과. 재현 스크립트: `results/_analysis_v2_2_stats.py`.
> 설계 전제: 추정 중심(효과크기+CI 1차, 유의성 보조). 사전 검정력 C4vsC5=0.09, C4vsC1=0.20 — "유의성 승리"는 구조적으로 불가(review_v2_2 §1).

## 0. 핵심 결론 (요약 8줄)

1. **RAG 효과는 크고 임계값에 robust하다.** C3_rag 65.0% vs C1_A 31.7% (+33.3%p, Newcombe CI[+20.7,+43.9], Cohen h=0.68 large). 0.6/0.7 임계에서도 RAG 1위 유지(45%) — V2.1의 치명적 "0.5 인공물"이 **재현되지 않았다.**
2. **GitOps는 placebo와 동률 = 길이만큼의 효과(=0).** C2_gitops 36.7% = C5_placebo 36.7%. GitOps main effect = −0.0%p (부트스트랩 CI[−5.8,+5.8]). 주입 fault에 GitOps 컨텍스트가 "Ready/무관"이라 진단 신호 없음.
3. **길이 효과(placebo)는 거의 0.** C5−C1 = +5.0%p (CI[−4.7,+14.6], 0 포함). RAG 우위는 토큰 증가가 아니라 **내용**. V2.1 대안가설 (b)"길이 교락"은 이번 설계로 **배제됐다.**
4. **그러나 RAG의 정체는 "추론"이 아니라 "정답 누출(retrieval leakage)"일 개연성이 매우 높다.** 60 RAG trial 중 45건(75%)에서 retriever가 **주입된 fault 바로 그 런북**(예: `rca-f11-networkdelay.md`, 제목에 정답 "NetworkDelay")을 회수. 자기 런북 회수 시 71%, 미회수 시 47%.
5. **both(C4) < RAG-only(C3): GitOps 추가가 RAG를 해친다.** interaction = −10.0%p (CI[−21.7,+0.0]), C4−C3 = −5.0%p. GitOps 무관신호가 RAG 정답런북을 희석/오도(특히 F12: C3 80%→C4 40%).
6. **수집 교란이 RAG의 가장 극적인 수치에 직격.** RAG net/node 80%(C1 20%) 우위는 거의 전부 F11/F12이고, 이는 1차(F1–F8t4)와 다른 2차 캠페인(06-21~22, GitOps 복구 후) 수집. arm 간 비교는 동일신호 공유로 내적 타당하나, **카테고리 간 비교는 시점 교락**.
7. **측정 robustness가 V2.1 대비 크게 개선.** judge 다수결 m=3 만장일치 286/300(95%), gen_agreement(k=3) 평균 0.76, low_quality_flag 0/300, judge blinding 코드 확인(arm 식별자 미전달 → self-preference 차단).
8. **추정 판정:** RAG **내용** 효과는 방향·크기·robustness 모두 강하게 지지되나 메커니즘이 **정답 누출**이라 "LLM이 RAG로 더 잘 추론한다"가 아니라 "fault에 맞는 런북을 찾아주면 라벨을 베낀다"에 가깝다. GitOps 길이효과=0, interaction 음(−). 논문 주장은 "RAG 런북 회수가 라벨 정확도를 올린다(검색 누출 통제 전까지 reasoning 기여로 해석 금지)"까지만 가능.

## 1. 데이터 검증 (verification-before-completion)

실행 명령·결과:
- `wc -l results/experiment_results_v2_2.csv` → 302 (헤더 1 + 데이터 **300**)
- `ls results/raw_v2_2/*.json | wc -l` → **300**
- `wc -l results/ground_truth.csv` → 61 (헤더 1 + 60 정답)

csv.DictReader 파싱:

| 항목 | 값 | 확인 |
|---|---|---|
| 데이터 행 | 300 | 5 arm × 60 = 300 |
| arm 분포 | C1_A 60 / C2_gitops 60 / C3_rag 60 / C4_both 60 / C5_placebo 60 | 균형 |
| fault | F1–F12 (12종) | 정상 |
| trial | 1–5 (각 60행) | 정상 |
| (fault,trial,arm) 중복 | **없음** | 무결 |
| rep_correctness_score 결측 | **0** | 무결 |
| low_quality_flag=1 | **0/300** | 신호 결손 자체 플래그 없음 |
| correct_at_0.5/0.6/0.7 (CSV native) vs 재계산 | **완전 일치**(19/22/39/36/22 @0.5) | 독립 검증 통과 |

raw 300 = CSV 300행과 1:1 (V2.1과 달리 SKIP 마커 없음 — 모든 (fault,trial,arm) 유효 수집).

### 1-1. 두 sub-campaign 수집 경위 (내적 타당성 교란)

timestamp 범위 fault별 추출(직접 명령):

| fault | 수집 시점 | 캠페인 |
|---|---|---|
| F1–F7 | 2026-06-20 14:36 ~ 19:59 | **1차** |
| F8 | 06-20 20:20 ~ **06-21 22:31** | 1차(t1–t4) + 2차(t5) 걸침 |
| F9–F12 | 06-21 22:41 ~ 06-22 00:54 | **2차** (GitOps 복구 후) |

로그 확증(/tmp/v2_2_full.log, /tmp/v2_2_rerun_F9_F12.log): 1차 F8t4가 readinessProbe 패치로 shippingservice 손상→F8t5–F12 21 trial validator SKIP. 2차에서 GitOps 복구(recovery.py 매니페스트 경로 버그 우회) 후 F8t5+F9–F12 재수집. F9t4는 1회 재skip 후 개별 재실행(로그 `===== RERUN F9 =====`).

**교란 범위 한정(중요):** 5-arm은 (fault,trial)당 **동일 신호** 공유(arm은 cooldown 불변, LLM 호출만 증가) → **arm 간 비교(C3 vs C1)는 시점 무관 내적 타당**. 그러나 **fault 간·카테고리 간 비교(service vs node/network)는 시점 교락**: net(F11/F12)은 전적으로 2차이므로 "RAG가 네트워크 fault에 강하다"는 시점·복구이력과 분리 불가.

## 2. 통계 분석

### 2.1 arm별 정확도 + 임계 sweep

| arm | @0.5 | @0.6 | @0.7 |
|---|---|---|---|
| C1_A (baseline) | 19/60 = **31.7%** | 14/60 = 23.3% | 13/60 = 21.7% |
| C2_gitops | 22/60 = 36.7% | 15/60 = 25.0% | 13/60 = 21.7% |
| C3_rag | 39/60 = **65.0%** | 27/60 = 45.0% | 27/60 = 45.0% |
| C4_both | 36/60 = 60.0% | 22/60 = 36.7% | 21/60 = 35.0% |
| C5_placebo | 22/60 = 36.7% | 14/60 = 23.3% | 13/60 = 21.7% |

**임계 sweep robustness (V2.1 0.6 역전과 대조):**
- 0.5: C3(65) > C4(60) > C2(37) ≈ C5(37) > C1(32)
- 0.6: C3(45) > C4(37) > C2(25) > C1(23) ≈ C5(23)
- 0.7: C3(45) > C4(35) > C1(22) ≈ C2(22) ≈ C5(22)

→ **C3 1위·C4 2위가 세 임계 모두 불변.** V2.1은 0.6에서 A/B 역전(0.5 인공물)했으나 V2.2는 RAG 우위가 임계 robust. 다수결(k=3 생성+m=3 채점)이 채점노이즈 흡수. score=0.5 경계 의존: C3 정답 39 중 12(31%), C4 36 중 14(39%) — V2.1 B 48%보다 낮고 0.6/0.7에서도 유지 → 경계 인공물 아님.

### 2.2 paired 효과크기 + Newcombe CI (1차 지표) @0.5

vs C1_A:

| arm | diff | Newcombe CI | Cohen h | (b,c) |
|---|---|---|---|---|
| C2_gitops | +5.0%p | [−2.2,+12.2] (0 포함) | +0.11 negligible | (4,1) |
| **C3_rag** | **+33.3%p** | **[+20.7,+43.9]** | **+0.68 large** | (20,0) |
| **C4_both** | **+28.3%p** | **[+16.5,+38.6]** | **+0.58 med-large** | (17,0) |
| C5_placebo | +5.0%p | [−4.7,+14.6] (0 포함) | +0.11 | (6,3) |

핵심 게이트:

| 대비 | diff | Newcombe CI | Cohen h | 해석 |
|---|---|---|---|---|
| **C4 − C5 (내용>길이)** | +23.3%p | [+11.3,+34.0] | +0.47 | CI>0 → both 내용효과 길이 초과 |
| **C3 − C5 (RAG 내용>길이)** | +28.3%p | [+15.5,+39.4] | +0.58 | CI>0 → RAG 내용효과 ✔ |
| C2 − C5 (GitOps 내용>길이) | **0.0%p** | [−7.9,+7.9] | 0.00 | GitOps = placebo |
| C4 − C3 (GitOps가 RAG에 추가) | −5.0%p | [−12.1,+2.2] | −0.10 | GitOps 추가가 손해(방향 음) |

→ 추정 게이트 C4>C5>C1 충족(60.0>36.7>31.7), 단 C5≈C1(길이효과 미미). "내용 순기여" 방향 지지하나 출처는 거의 전적으로 **RAG**(C3)이고 GitOps(C2)=0.

### 2.3 2×2 factorial 분해 (GitOps × RAG)

| thr | GitOps main | RAG main | interaction | placebo(C5−C1) |
|---|---|---|---|---|
| 0.5 | **−0.0%p** | **+28.3%p** | **−10.0%p** | +5.0%p |
| 0.6 | −3.3%p | +16.7%p | −10.0%p | 0.0%p |
| 0.7 | −5.0%p | +18.3%p | −10.0%p | 0.0%p |

부트스트랩(10k, fault를 cluster로 resample) @0.5: GitOps main +0.0%p CI[−5.8,+5.8] **0과 무구별**; RAG main +28.5%p CI[+14.2,+44.2] **강건 양(+)**; interaction −10.1%p CI[−21.7,+0.0] **음 방향, 상한 0 접촉**.

해석: RAG 주효과만 살아남음. GitOps 0, interaction 음 — 두 처치는 시너지 아니라 **간섭**. (GitOps/RAG 중복 마스킹 아님: jaccard 평균 0.040, max 0.061, >0.3 0건. 간섭은 중복이 아니라 GitOps 무관신호의 컨텍스트 오염.)

### 2.4 보조 유의성(McNemar exact) + 검정력 경고

trial-level (n=60 pairs, 반복측정 독립취급 → 거짓 정밀도 위험):

| 대비 | b | c | exact p |
|---|---|---|---|
| C3 vs C1 | 20 | 0 | <0.0001 |
| C4 vs C1 | 17 | 0 | <0.0001 |
| C3 vs C5 | 18 | 1 | 0.0001 |
| C4 vs C5 | 15 | 1 | 0.0005 |
| C2 vs C1 | 4 | 1 | 0.375 ns |
| C4 vs C3 | 1 | 4 | 0.375 ns |

fault-집계 majority (12 item, 반복측정 정석에 더 근접):

| 대비 | b | c | exact p |
|---|---|---|---|
| C3 vs C1 | 6 | 0 | **0.031** |
| C4 vs C1 | 6 | 0 | **0.031** |
| C3 vs C5 | 6 | 1 | 0.125 ns |
| C4 vs C5 | 5 | 0 | 0.063 ns |

**검정력 경고(필수):** 사전 power C4vsC5=0.09, C4vsC1=0.20(review §1). trial-level의 극소 p(<0.0001)는 반복측정 60건을 독립 취급한 **거짓 정밀도**(한 fault 5 trial 모두 맞으면 5 독립증거로 셈). 정석 fault-집계(12 item)에선 RAG vs C1만 p=0.031로 살고 **내용>길이 게이트(C3/C4 vs C5)는 비유의(0.063~0.125)**. 즉 "RAG>baseline"은 보조 유의성도 지지하나 "RAG 내용>길이"는 검정력 부족으로 비유의. **비유의≠효과없음**: 효과크기 추정(h=0.58, CI>0)은 양의 방향 강하게 시사. 추정 중심 프레이밍이 이 한계를 정직히 드러냄.

### 2.5 fault별 forest (RAG main effect 분해) + 카테고리

| fault | C1 | C2 | C3 | C4 | C5 | RAG main | GitOps main | cat |
|---|---|---|---|---|---|---|---|---|
| F1 OOM | .4 | .4 | .4 | .4 | .4 | +0 | +0 | service |
| F2 CrashLoop | .4 | .4 | .8 | .6 | .2 | +30 | −10 | service |
| F3 ImagePull | .6 | .6 | .8 | .6 | .6 | +10 | −10 | service |
| F4 NodeNotReady | .6 | .4 | .6 | .6 | .4 | +10 | −10 | node |
| F5 | .2 | .4 | .4 | .4 | .4 | +10 | +10 | service |
| F6 | .4 | .4 | .4 | .4 | .4 | +0 | +0 | service |
| F7 | .2 | .6 | 1.0 | 1.0 | .8 | +60 | +20 | service |
| F8 | .2 | .2 | .6 | .6 | .2 | +40 | +0 | service |
| F9 Secret | .4 | .4 | .6 | .6 | .4 | +20 | +0 | service |
| F10 | .4 | .4 | .4 | .6 | .6 | +10 | +10 | service |
| **F11 NetDelay** | **.0** | .2 | **1.0** | 1.0 | .0 | **+90** | +10 | net |
| **F12 NetLoss** | **.0** | .0 | **.8** | .4 | .0 | **+60** | −20 | net |

RAG main effect: service 평균 +20.0%p(9 fault), node/net 평균 **+53.3%p**(3 fault).

카테고리별 정확도 @0.5:

| arm | service (45) | node/net (15) |
|---|---|---|
| C1_A | 35.6% | 20.0% |
| C2_gitops | 42.2% | 20.0% |
| C3_rag | 60.0% | **80.0%** |
| C4_both | 57.8% | 66.7% |
| C5_placebo | 44.4% | 13.3% |

**비판:** V2.1은 우위가 단일 fault(F4) 편중. V2.2 RAG는 **F4식 단일 편중 아님** — service 9개 중 7개에서 RAG main ≥+10%p(분산). 그러나 가장 극적 수치는 **F11/F12(+90/+60%p)에 집중**, 이 둘은 ① C1 0%(개선 여지 최대) ② 전적으로 2차 캠페인(시점 교락) ③ §2.6의 정답 런북 누출. net 제외 시 RAG service 효과(+20%p)는 실재하나 크기 절반 이하.

### 2.6 ⚠️ 대안가설 검증: RAG 정답 누출 (가장 중요)

raw context 직접 파싱(60 C3_rag에서 `runbooks/rca-(f\d+)-` 추출):
- 60 RAG trial 중 **45건(75%)**에서 retriever가 **주입 fault 바로 그 런북** 회수. 예: F11 trial RAG 컨텍스트에 `[Source: runbooks/rca-f11-networkdelay.md]`, 제목이 곧 정답("NetworkDelay").
- 자기 런북 회수 시 RAG 정확도 **32/45=71%**, 미회수 시 **7/15=47%**.

**construct validity 결함.** 런북 파일명·제목·trigger 조건이 정답 라벨을 거의 직접 담아(파일명 `rca-f11-networkdelay`) LLM이 회수 문서 제목을 라벨로 베꼈을 개연성. 특히 C1 0%인 F11/F12에서 RAG 100%/80%는 — 관측신호(메트릭 "No anomalies", 로그 거의 없음)로는 불가능하던 진단이 정답 명시 런북이 주어지자 가능해진 것. RAG 효과 상당부분이 **"검색 정답지"**.

배제된 다른 대안가설:
- **(judge가 RAG 답에 후함)** → **배제.** blinding 코드 확인(engine.py:68 judge_voted_blinded): 채점 입력에 arm 식별자·출처(GitOps/RAG/obs) 미포함, 진단+근거+정답만 전달.
- **(길이 효과)** → **배제.** C5=C2≈C1, placebo 내용은 무의미 보일러플레이트(raw 확인).
- **(GitOps/RAG 중복 마스킹)** → **배제.** jaccard 0.04.
- **(단일 fault 편중)** → **부분 배제.** 분산되나 net 2개 극단 집중.

### 2.7 측정 robustness 자체 평가

| 지표 | 값 | V2.1 대비 |
|---|---|---|
| gen_agreement (k=3) | 평균 0.762, 중앙 0.667 (만장일치 134/2:1 합의 118/분열 48) | 분포 도입 ✔ |
| judge 만장일치 (m=3) | **286/300 (95.3%)**, 분열 14 | 채점 비결정성 흡수 |
| low_quality_flag=1 | 0/300 | 2차 복구 후 안정 |
| gitops_rag_jaccard | 평균 0.040, max 0.061 | 중복 통제 ✔ |
| judge blinding | 코드 확인(arm 미전달) | self-preference 차단 ✔ |

→ V2.1 채점 비결정성·단일측정·길이교락·blinding 부재 결함 **모두 구조 개선**. 단 gen_agreement 분열 48(16%)은 일부 fault 생성 불안정. low_quality_flag 0은 "2차가 깨끗"일 뿐 1차 F8 손상 같은 상위 교란은 못 잡음(플래그는 신호수집 레벨만).

## 3. 비판적 회고 — Plan Critique 5축 (선행연구 정량 인용)

### ① 구성 타당성
**부분 위반(누출).** 5-arm factorial+placebo는 V2.1 묶음처치·길이교락을 정확히 해소(설계 진전). 그러나 **RAG arm 처치가 사실상 "정답 라벨 주입"으로 오염**(§2.6: 75% 자기런북, 71% vs 47%). "RAG가 추론을 돕는다"가 "RAG가 정답지를 회수한다"로 붕괴.
선행연구: Flow-of-Action(docs/papers/flow-of-action.md)은 SOP를 `name`+`steps`로 구조화해 ReAct 35.5%→64.0%, ablation SOP 제거 −38.67pp 분리측정. 우리 런북은 "참조 문서"이지 "실행 절차"가 아니고 제목에 정답 노출 → *절차 지식 주입*이 아니라 *정답 회수*. 개선: 런북 제목/파일명에서 fault 라벨 제거(blind retrieval).

### ② 내적 타당성
**arm 비교 통제(동일신호), 카테고리 비교 교란.** §1-1: F11/F12 2차 전용 → RAG net 80% 우위는 시점·GitOps복구이력과 분리 불가. arm 간(C3 vs C1)은 같은 (fault,trial) 신호 → 시점 무관 타당(V2.2 핵심 강점). 잔존 위협: F8 t1–t4 vs t5 셀 내부 시점 혼재.
선행연구: SynergyRCA(위키 concepts/LLM 기반 RCA.md 경유, precision~0.90)는 StateChecker로 후보 원인 사실/인과 정합성을 설명 전 검증 — 우리는 사전 정합성 검증 없어 누출 정답 그대로 통과.

### ③ 외적 타당성
**제한적(설계서 §8 사전선언).** 단일 클러스터(KT Cloud Debian 6노드, Cilium)·앱(Online Boutique)·모델(gpt-4o-mini)·**런북 1종**·trial=5. RAG 효과는 **런북 품질·제목 규약에 종속**(제목 정답 노출)이라 다른 KB로 일반화 불가.
선행연구: 우리 RAG 65%(C3)는 CoT 32.6%·ReAct 35.5% 위, Flow-of-Action 64.0%(GPT-4-Turbo) 동급, SynergyRCA~0.90 아래. 단 65%는 **정답 누출 보정 전** → 누출 통제(blind retrieval) 후 재측정 전까지 "Flow-of-Action 동급" 주장 불가.

### ④ 통계 타당성
**추정 견고, 유의성은 검정력 한계.** Newcombe CI·Cohen h·부트스트랩으로 방향·크기 정직 추정(RAG main CI[+14.2,+44.2] 강건). 정석 fault-집계(12 item) 내용>길이 게이트는 비유의(0.063~0.125), 사전 power 0.09~0.20 실측 확인. statsmodels 부재로 GLMM 미실행 → **fault-cluster 부트스트랩 대체**(명시). 반복측정 random effect 정식 모델링 못한 한계.
선행연구: 다수 LLM-RCA가 검정·CI 생략 — 우리 CI·검정력 명시는 차별점이나 trial 증량 필요(review §1: trial=20에도 C4vsC5 power 0.46).

### ⑤ 대안 가설
**가장 유력 대안(정답 누출)이 능동 검증으로 지지**(§2.6). interaction 음(−)은 "GitOps+RAG 시너지" 순진한 기대 반증. 길이·judge편향·중복 배제. V2.2가 배제한 V2.1 대안가설=길이·채점노이즈, **새 부상 대안=검색 정답 누출**.
선행연구: Auditable Graph-Guided RCA(위키 sources/2026-06-20-...검증-아이디어.md) claim-audit 4단계 중 **telemetry 누출검사·prompt-ablation**이 §2.6 누출 체계화 도구 — 다음 라운드 적용 권장.

## 4. 개선 가설 (V2.3 후보, 우선순위순)

**P1(최우선) — RAG 정답 누출 제거 + ablation.** 근거(데이터): §2.6 75% 자기런북, 71% vs 47%. 개선: ① 런북 제목/파일명 fault 라벨 마스킹(blind retrieval), ② "정답 런북 회수됨" 플래그 후 회수/미회수 stratified 정확도, ③ retrieval을 절차(steps)만·진단명 제거(Flow-of-Action식). 통제 후 RAG 우위 잔존 시 진짜 추론 기여. 근거(논문): Flow-of-Action(name/steps, −38.67pp), Auditable-RCA(누출검사).

**P2 — 검정력 확보(trial 증량), 단 한계 인지.** 근거: fault-집계 내용>길이 비유의(0.063~0.125), 사전 power 0.09~0.20. 개선: trial 5→15~20(review §1: C4vsC1 power 0.83@t10). 단 C4vsC5는 t20에도 0.46 → 유의성보다 **효과크기·CI 정밀화**가 현실 목표.

**P3 — GitOps 신호를 진단가능하게(왜 placebo 수준인가).** 근거: GitOps main=0, C2=C5. raw 확인 결과 GitOps 블록이 fault 무관 "Ready" + 잘못된 `Git repo not found at /tmp/thesis-rca-work`(복구 버그 잔재). 개선: GitOps 컨텍스트를 fault와 연동(Git 매니페스트 경유 주입, 또는 drift/sync 실패 반영). imperative 주입이면 GitOps 구조적 무신호 → "GitOps 무효"는 주입방식의 산물일 수 있음(대안가설).

**P4 — interaction 음(−) 원인 ablation.** 근거: interaction −10%p, C4<C3, F12 C3 80%→C4 40%. GitOps 무관신호가 RAG 정답런북 희석. 개선: 컨텍스트 순서·위치 통제(Lost in the Middle), GitOps/RAG 분리 배치 arm 추가.

**P5 — 카테고리 시점 교락 제거.** 근거: §1-1 F11/F12 전용 2차. 개선: F1–F12 동일 캠페인·동일 복구이력 재수집.

## 5. 결론 · 한계

**추정 판정:**
- **RAG 내용 효과**: 방향(+)·크기(large, h=0.58~0.68)·임계 robustness(0.5/0.6/0.7 모두 1위) 강하게 지지, 길이효과와 분리(C3−C5 CI>0). **그러나 메커니즘이 "추론 개선"이 아니라 "정답 런북 회수(검색 누출)"일 개연성 높음**(75% 자기런북, 71% vs 47%). 누출 통제 전까지 reasoning 기여로 해석 금지.
- **GitOps 길이 효과**: main=0, placebo 동률. imperative 주입 하 GitOps 컨텍스트 무신호(구조적). "GitOps 무용"은 주입방식 산물일 수 있어 단정 보류.
- **interaction**: 음(−10%p). GitOps+RAG는 시너지 아니라 간섭. "둘 다 넣으면 더 좋다" 반증.

**V2.1 대비 진전:** 채점 0.5 인공물 **해소**(임계 robust), 길이 교락 **분리**(placebo=0), 채점 비결정성 **완화**(m=3 만장일치 95%), judge 편향 **차단**(blinding). 설계 품질 명확 향상.

**일반화 한계:** 단일 클러스터·앱·모델·런북1종·trial=5. RAG 효과는 런북 제목 규약(정답 노출)에 종속돼 일반화 불가. net 카테고리는 2차 캠페인 시점 교락. 검정력 0.09~0.20으로 "내용>길이" 유의성 구조적 미달 — 추정 중심 해석만 유효.

**한 줄:** V2.2는 "GitOps+RAG가 RCA를 개선한다"가 아니라 **"fault에 맞는 런북을 회수해주면 LLM이 그 라벨을 정답으로 낸다(누출), GitOps는 imperative 주입 하 무신호, 둘의 결합은 간섭한다"**를 robust하게 추정한 라운드. 논문 주장으로 쓰려면 V2.3에서 **검색 누출을 통제**(P1)한 뒤 RAG 우위 잔존 여부 재확인 필요.

## 부록 A — 실행한 검증 명령

```
wc -l results/experiment_results_v2_2.csv          # 302 (data 300)
ls results/raw_v2_2/*.json | wc -l                 # 300
wc -l results/ground_truth.csv                     # 61 (60 정답)
.venv/bin/python -c "import statsmodels"            # ModuleNotFoundError → 부트스트랩 대체
.venv/bin/python results/_analysis_v2_2_stats.py    # arm acc·Newcombe CI·Cohen h·factorial·부트스트랩·McNemar·forest·robustness
# raw 누출: 60 C3_rag context에서 runbooks/rca-(f\d+) 추출 → 45/60 자기런북, 71% vs 47%
# 길이통제: C5_placebo context = 무의미 보일러플레이트 직접 확인
# GitOps 무신호: C2 context = "Ready" + "Git repo not found" 직접 확인
# blinding: experiments/v2_2/engine.py:68 judge_voted_blinded — arm 미전달 확인
# CSV-native correct@thr vs 재계산 일치: 19/22/39/36/22 @0.5
# timestamp per-fault: F1–F8t4 06-20(1차), F8t5–F12 06-21~22(2차) — 캠페인 교락 확인
```

## 부록 B — 인용 선행연구
| 출처 | 위치 | 정량 | 신뢰도 |
|---|---|---|---|
| Flow-of-Action (WWW2025, 2502.08224) | docs/papers/flow-of-action.md | GPT-4-T 64.0%; SOP 제거 −38.67pp; CoT 32.6/ReAct 35.5/K8SGPT 11.1 | HIGH(1차) |
| Self-Consistency (Wang, 2203.11171) | deep_analysis_v2_2 | GSM8K +17.9%p, T=0.7 | HIGH |
| LLM-judge 비결정 (2503.09347) | deep_analysis_v2_2 | GPT-4T 5.7% 투표변동 | MEDIUM |
| MT-Bench judge (2306.05685) | deep_analysis_v2_2 | ref-guided 70→15% 추론실패↓ | HIGH |
| Power of Noise (2401.14887) | deep_analysis_v2_2 | 무관문서 +~35%(역설) | MEDIUM |
| SynergyRCA (2506.02490) | 위키 concepts/LLM 기반 RCA.md 경유 | precision~0.90, StateChecker | MEDIUM(원논문 표 1차 미확인) |
| Auditable Graph-Guided RCA (2606.08590) | 위키 sources/2026-06-20-...검증-아이디어.md | claim-audit 4단계(누출검사) | MEDIUM |
| Newcombe(1998)/Cohen(1988)/Czitrom(1999) | 방법론 | hybrid score CI / h / factorial | HIGH |

> 신뢰도 주: Flow-of-Action·Newcombe/Cohen은 1차/표준. SynergyRCA·Auditable-RCA 수치는 위키 기록 인용(원논문 표 1차 미확인 → MEDIUM). GLMM은 statsmodels 부재로 fault-cluster 부트스트랩 대체(명시). 모든 통계 수치는 본 분석가가 직접 계산.
