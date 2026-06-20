# V2.1 실험 결과 비판적 분석 (독립 분석가)

> 작성: 2026-06-20 · 분석 대상: results/experiment_results_v2_1.csv (120행) + results/raw_v2_1/*.json (118개)
> 입장: 이 실험을 수행한 오케스트레이터와 분리된 fresh 시각. "B>A로 성공했다"는 확증 편향을 경계하고 결함·교란·한계를 능동적으로 탐색했다.
> 모든 수치는 본 분석가가 .venv/bin/python으로 직접 계산한 명령 결과에 근거하며, 오케스트레이터가 헤드라인 통계(정확도·McNemar·임계 민감도·카테고리)를 독립 재계산해 일치 확인했다.

## 0. 핵심 결론 (요약)

1. B>A는 통계적으로 유의하지 않다. McNemar χ²(연속성 보정)=1.23, p=0.267; 정확검정(binomial) p=0.267. 불일치 쌍이 b=4(A맞B틀), c=9(A틀B맞)로 방향은 B 우위이나 n=13으로 표본 부족. α=0.05에서 귀무가설(A=B) 기각 불가.
2. B의 우위는 채점 임계값 0.5에 전적으로 의존하는 인공물이다. correctness_score 임계를 0.6으로만 올려도 우위가 역전된다(A 25.9% vs B 22.4%). B의 25개 정답 중 12개(48%)가 정확히 경계값 0.5("부분 정답")다.
3. 네트워크 fault(F11/F12)는 사실상 전멸(A 0/10, B 1/10)이며, 그 1건(F12 t2 B)조차 A와 거의 동일한 답("Network Delay")인데 LLM 채점기가 A=0.1/B=0.5로 갈라 채점한 채점 비결정성의 산물이다.
4. LLM-judge 평가점수(grounding 8.8~9.1/10)는 실제 정확도(34~43%)와 완전히 괴리되어 있어, eval 4지표를 품질 근거로 쓸 수 없다.
5. 데이터 무결성 자체는 깨끗하다(120행=116유효+4 skip, raw 118=116유효+2 SKIPPED 마커). 그러나 F11/F12 별도 수집 시점·고손실 trial의 신호 누락이라는 내적 타당성 교란이 실재한다.

판정: 이번 라운드 가설(B>A)은 "방향은 지지, 통계적·방법론적으로는 미입증". re-baseline으로서 데이터 수집 파이프라인은 동작했으나, 결과를 논문 주장으로 쓰기엔 채점 robustness와 표본이 부족하다.

## 1. 데이터 검증 (verification-before-completion)

실제 실행 명령과 결과:
- wc -l results/experiment_results_v2_1.csv → 121 (헤더 1 + 데이터 120)
- ls results/raw_v2_1/*.json | wc -l → 118

파싱 결과(csv.DictReader):
| 항목 | 값 | 확인 |
|---|---|---|
| 데이터 행 | 120 | system A 60 / B 60 |
| fault | F1–F12 (12종) | 정상 |
| trial | 1–5 | 정상 |
| (fault,trial,system) 중복 | 없음 | 무결 |
| skipped=true | 4행 | F2 t5 (A,B), F3 t3 (A,B) |
| validator_status | clean 112 / corrected 4 / skipped 4 | — |

120 vs 118 불일치 해소(추적 완료):
- 유효 trial 116행 = 각 1개 raw JSON → 116개
- skip된 4행(F2t5·F3t3 × A/B)은 fault/trial 단위로 묶여 raw에 *_SKIPPED_*.json 마커 2개로 저장(F2_t5_SKIPPED_20260619_222133.json, F3_t3_SKIPPED_20260619_225128.json).
- 즉 118 = 116 유효 + 2 skip 마커. 누락·과잉 없음.

skip/validator 통계:
- validator가 corrected 4건(잔류 fault 자동 정정 성공), skipped 2 fault/trial(=CSV 4행, 정정 실패 → 통계 제외). V9 Pre-Trial State Validator가 설계대로 동작(skip은 분모에서 제외).
- 유효 분석 분모 = system당 58 (=60−2 skip).

수집 경위 검증(로그 인용): F11/F12는 06-20 11:38~12:16 별도 캠페인(/tmp/f11_f12_campaign.log)에서 재수집됨이 확인된다. 고강도 trial에서:
- "Recovery failed: ... tc qdisc del dev vmbr0 ... timed out after 15 seconds" 3건(11:45, 11:54, 12:16) → 즉시 recovery 실패, 주입 시 (sleep 300 && tc qdisc del) 안전망으로만 정리됨이 로그로 확인.
- "Loki query error: Read timed out (read timeout=30)" 2건(12:05, 12:06) → F12 고손실 trial 구간에서 로그 신호 부분 누락 확정.

## 2. 통계 분석

### 2.1 전체 정확도 (분모 = 58, skip 제외)
| System | 정답/분모 | 정확도 |
|---|---|---|
| A (베이스라인) | 20/58 | 34.5% |
| B (제안) | 25/58 | 43.1% |
| 차이 | +5 | +8.6%p |

참고: F1–F10만 보면 A 20/48=41.7%, B 24/48=50.0% (중간보고서 수치와 일치 확인). F11/F12를 포함하면 두 시스템 모두 하락 — 즉 네트워크 fault가 전체 정확도를 끌어내린다.

### 2.2 McNemar 검정 (paired, skip 제외)
(fault,trial) 쌍별 A/B 정답 분할표:
|  | B 정답 | B 오답 |
|---|---|---|
| A 정답 | 16 | 4 (=b) |
| A 오답 | 9 (=c) | 29 |

- McNemar χ²(연속성 보정) = (|9−4|−1)²/13 = 1.231, p=0.267
- McNemar χ²(무보정) = 1.923, p=0.166
- 정확검정(binomial, n=13, k=4, two-sided): p=0.267

판정: p=0.267 > 0.05 → B>A는 통계적으로 유의하지 않다. 방향성은 B 우위(c=9 > b=4)이나 표본 부족.

### 2.3 채점 임계값 민감도 (가장 치명적 발견)
correctness_score ≥ threshold → correct 로 재계산:
| threshold | A 정확도 | B 정확도 | gap | McNemar(b,c) exact p |
|---|---|---|---|---|
| 0.5 (현행) | 34.5% | 43.1% | +8.6%p | (4,9) 0.267 |
| 0.6 | 25.9% | 22.4% | −3.4%p (역전) | (3,1) 0.625 |
| 0.7 | 25.9% | 22.4% | −3.4%p | (3,1) 0.625 |

B의 25개 정답 중 12개(48%)가 정확히 score=0.5 "부분 정답"(A는 20개 중 5개만 0.5). 즉 B의 우위는 "정답에 가까운 부분 정답"을 0.5 경계에서 정답으로 집계한 결과이며, 합리적인 임계 변경 한 번에 결론이 뒤집힌다. 이 결과는 robust하지 않다. (오케스트레이터 독립 재계산: 0.6/0.7 임계에서 A 25.9% vs B 22.4% 역전 확인.)

### 2.4 fault별 정확도 (분모 = 비-skip trial 수)
| fault | A | B | 비고 |
|---|---|---|---|
| F1 OOMKilled | 2/5 | 2/5 | 동률 |
| F2 CrashLoop | 0/4 | 2/4 | B 우위(둘 다 score 0.5 경계) |
| F3 ImagePull | 2/4 | 2/4 | 동률 |
| F4 NodeNotReady | 1/5 | 4/5 | B 최대 우위 |
| F5 | 2/5 | 1/5 | A 우위 |
| F6 | 1/5 | 1/5 | 둘 다 취약 |
| F7 | 4/5 | 5/5 | 둘 다 강함 |
| F8 | 1/5 | 1/5 | 둘 다 취약 |
| F9 | 3/5 | 3/5 | 동률 |
| F10 | 4/5 | 3/5 | A 우위 |
| F11 NetworkDelay | 0/5 | 0/5 | 전멸 |
| F12 NetworkLoss | 0/5 | 1/5 | 거의 전멸 |

### 2.5 카테고리별 (service vs node)
| 카테고리 | A | B |
|---|---|---|
| service (F1–3,5–10) | 19/43 = 44.2% | 20/43 = 46.5% |
| node (F4,F11,F12) | 1/15 = 6.7% | 5/15 = 33.3% |

B의 전체 우위는 거의 전적으로 node-level, 특히 F4(NodeNotReady)에서 나온다(B 4/5 vs A 1/5). service-level만 보면 차이는 +2.3%p로 미미. 즉 "B가 GitOps/RAG로 RCA 전반을 개선"이 아니라 "B가 노드 장애 한 종류(F4)를 더 잘 맞춤"에 가깝다.

### 2.6 평가 4지표 + overall (mean / median, n=58)
| 지표 | A mean | A med | B mean | B med |
|---|---|---|---|---|
| evidence_grounding | 8.79 | 9 | 9.09 | 9 |
| diagnostic_logic | 7.98 | 8 | 8.07 | 8 |
| differential_completeness | 7.07 | 7 | 7.09 | 7 |
| confidence_calibration | 7.74 | 8 | 7.86 | 8 |
| overall | 7.90 | 8 | 8.02 | 8 |

비판: 정확도는 34~43%인데 LLM-judge가 매긴 evidence_grounding은 8.8~9.1/10. 평가점수와 정답 여부가 거의 무상관(틀린 답에도 9점대 grounding 부여). 이는 LLM-as-judge의 알려진 점수 인플레이션·관대화 편향이며, eval 4지표를 품질 우월성 근거로 인용해서는 안 된다.

### 2.7 신뢰도 보정 (correct vs wrong 시 confidence)
| System | 맞을 때 conf | 틀릴 때 conf | gap |
|---|---|---|---|
| A | 0.815 (n=20) | 0.816 (n=38) | −0.001 |
| B | 0.852 (n=25) | 0.792 (n=33) | +0.060 |

A는 신뢰도 보정이 완전히 망가져 있다(맞든 틀리든 신뢰도 0.81로 동일). 특히 F11/F12에서 A는 "No Issues Detected"를 confidence 1.0으로 단언(F11 t1·t2, F12 t1) — 위험한 false-negative 과신. B는 약한 양의 gap이나, 여전히 틀릴 때도 평균 0.79로 과신.

### 2.8 비용 (A vs B)
|  | latency(평균/중앙) | prompt_tok | completion_tok |
|---|---|---|---|
| A | 9,922 / 9,586 ms | 4,858 | 1,003 |
| B | 10,531 / 10,654 ms | 6,686 | 1,063 |

B는 prompt 토큰 +38%(GitOps+RAG 컨텍스트), latency +6%를 지불하고 정확도 +8.6%p(유의하지 않음)를 얻는다. 비용 대비 효익이 입증되지 않았다.

### 2.9 F11/F12 심층 (node-level 네트워크)
12 trial 전부 raw 확인 결과:
- A는 fault를 아예 부정: "No Issues Detected/No Fault Detected/None Detected"를 conf 0.5~1.0으로 5회. 네트워크 지연/손실 신호를 메트릭/로그에서 못 읽음.
- B는 오진: "GitOps Deployment Failure", "Duplicate Port Configuration", "Configuration Issue" 등 — RAG/GitOps 컨텍스트가 오히려 설정 오류 쪽으로 오도(node-level 네트워크 장애에 GitOps 단서가 무관함에도 끌려감).
- F12 t2 B "정답"의 실체(raw 직접 확인): A·B 모두 identified_fault_type="Network Delay", root_cause는 "TCP retransmission → service timeout"로 거의 동일. 정답은 NetworkLoss(30% packet loss)인데 둘 다 "Delay"로 오인. LLM 채점기가 A=0.1(오답)/B=0.5(정답)로 갈라 채점 → 동일 내용에 대한 채점 비결정성. 이 1건은 B의 실력이 아니라 채점 노이즈다.

결론: 네트워크 fault에서 B의 1/10은 통계적 의미가 없고, RAG가 오히려 해를 끼친 정황(설정 오류 오도)이 보인다.

## 3. 비판적 회고 — Plan Critique 5축 (선행연구 정량 인용 포함)

### ① 구성 타당성 — 독립변수가 정확히 1개인가?
부분 위반. 명목상 독립변수는 "GitOps 컨텍스트 + RAG 런북"이지만 이는 사실상 두 개의 묶음 처치(GitOps 컨텍스트 ∪ RAG 런북)다. 어느 쪽이 +8.6%p에 기여했는지 분리 불가. 또한 B는 prompt 토큰 +38%로 컨텍스트 길이 자체가 동반 변동하므로, "내용(GitOps/RAG)" 효과와 "더 긴 컨텍스트" 효과가 교락된다.
선행연구 대비: Flow-of-Action(WWW 2025, docs/papers/flow-of-action.md)은 ablation으로 SOP 지식 주입의 기여를 −38.67pp(54%→15.4%)로 분리 측정했다. 우리 실험엔 GitOps만/RAG만/둘다 ablation이 없어 같은 분리가 불가능하다. 개선 필요: 처치를 GitOps-only / RAG-only / both 3-arm으로 분해.

### ② 내적 타당성 — 교란 통제
다수의 통제 실패 확인:
- F11/F12 수집 시점·조건 차이(확정): F1–F10은 06-19 1차, F11/F12는 06-20 별도 캠페인. 클러스터 상태·시간대가 다른 데이터를 한 표에 합산. node 카테고리 정확도(B 33.3%)는 이 시점 차이와 분리 불가.
- 고손실 trial 신호 누락(확정): F12 고손실 구간 Loki read timeout 2건 → 해당 trial RCA 입력 품질 저하. 그런데도 그 trial들을 정상 trial과 동일 가중으로 채점.
- 즉시 recovery 실패 → 300s 안전망 정리(확정): tc del 15초 타임아웃 3건. 다음 trial 시작 시점에 잔류 netem 룰이 남았을 가능성을 validator가 못 잡음(V9 validator는 deployment 레벨만 담당, 노드 레벨 tc 잔류는 recovery.py 책임 — 설계상 사각지대).
- 모델 비결정성(확정): F12 t2에서 동일 입력류에 A/B 채점이 0.1 vs 0.5로 갈림. temperature·채점기 비결정성이 통제되지 않음(seed 고정·다중 샘플 평균 부재).
선행연구 대비: SynergyRCA(arXiv 2506.02490, 위키 concepts/LLM 기반 RCA.md 경유)는 StateChecker로 후보 근본원인의 사실/인과 정합성을 LLM 설명 전에 검증해 precision ~0.90을 달성. 우리는 그런 사전 정합성 검증이 없어 채점·신호 노이즈가 그대로 결과에 유입된다.

### ③ 외적 타당성 — 일반화
제한적. 단일 클러스터(KT Cloud Debian 6노드, Cilium), 단일 앱(Online Boutique 12서비스), 단일 모델(gpt-4o-mini), trial당 1회 측정. 다른 토폴로지·앱·실서비스 트래픽으로의 일반화 근거 없음.
선행연구 대비: Flow-of-Action도 Online Boutique 90 incident·9 fault로 한정적이나 GPT-4-Turbo 기준 64% 달성. 우리 B 43.1%는 CoT(~33%)·ReAct(~35%) 위, Flow-of-Action(64%)·SynergyRCA(~0.90) 한참 아래에 위치. 모델 체급 차이를 감안해도 정확도 절대값이 낮아 일반화 주장이 약하다.

### ④ 통계 타당성 — 표본·검정 적절성
불충분. trial당 1회 측정, fault당 5 trial, 불일치 쌍 n=13. McNemar는 적절한 검정 선택이나 검정력이 매우 낮다(효과크기 +8.6%p 검출에 표본 부족). 신뢰구간·효과크기·다중비교 보정·반복측정이 모두 부재. §2.3에서 보듯 결론이 채점 임계값에 robust하지 않다는 점이 통계 타당성의 결정적 약점.
선행연구 대비: 위키에 기록된 다수 LLM-RCA 연구도 통계검정을 생략하는 경향(Flow-of-Action도 p값 없음)이 있어, 우리가 McNemar p값을 명시하면 오히려 차별점이 될 수 있다 — 단, 그러려면 표본을 늘려 유의성을 확보해야 한다.

### ⑤ 대안 가설 — B 우위가 RAG/GitOps 때문이 아닐 가능성
다음 대안이 모두 배제되지 않았다:
- (a) 채점 임계값 인공물(가장 유력): §2.3 — 0.6 임계에서 우위 역전. B 우위 = "부분 정답을 0.5에서 정답 처리"의 부산물.
- (b) 컨텍스트 길이 효과: B의 +38% 토큰이 단지 더 많은 단서를 제공해서일 수 있음(GitOps/RAG "내용"과 무관).
- (c) 단일 fault(F4) 우연 편중: B 전체 우위(+5건) 중 F4가 +3건. F4 5 trial의 표본 변동일 수 있음.
- (d) LLM 채점 비결정성: F12 t2처럼 동일 답이 갈려 채점된 사례 존재.
선행연구 대비: Auditable Graph-Guided RCA(arXiv 2606.08590, 위키 sources/2026-06-20-auditable-graph-guided-rca-검증-아이디어.md)의 claim-audit 4단계(동일판정기 비교 / prompt-ablation / telemetry 누출검사 / cascade 출처추적)를 적용하면 위 (a)~(d)를 체계적으로 배제할 수 있으나, 본 실험엔 미적용.

## 4. 개선 가설 (V2.2 후보, 우선순위순)

P1. 채점 robustness 확보 — multi-sample + 임계 민감도 보고 (필수·최우선)
- 근거(데이터): §2.3 — 결론이 0.5 임계에 의존, 0.6에서 역전. §2.9 — 동일 답 채점 갈림.
- 개선: ① 각 trial을 k=3~5회 반복 샘플해 정답률을 비율로 측정, ② 채점기도 다중 호출 다수결, ③ 임계값 sweep(0.5/0.6/0.7) 결과를 항상 병기. seed/temperature 고정.
- 근거(논문): self-consistency(다중 샘플 다수결)는 위키 RCA 계보에서 mABC 등이 채택. SynergyRCA의 StateChecker처럼 채점 전 사실 검증 도입 검토.

P2. 처치 분해 (GitOps-only / RAG-only / both) 3-arm ablation
- 근거(데이터): §3-① 독립변수가 묶음 처치. 어느 컴포넌트가 효과인지 모름.
- 근거(논문): Flow-of-Action ablation(docs/papers/flow-of-action.md)이 지식 주입 −38.67pp로 분리 측정한 방식 차용. 컨텍스트 길이 통제 arm(무관 텍스트로 토큰만 맞춘 placebo)도 추가해 길이 효과 배제.

P3. 네트워크 fault(F11/F12) 신호·진단 파이프라인 보강
- 근거(데이터): §2.5/2.9 — node-network 사실상 전멸. A는 부정·과신, B는 RAG가 설정오류로 오도.
- 개선: ① netem delay/loss를 잡는 전용 메트릭(node_network_*, TCP retransmit, Cilium drop) 명시 수집 + 프롬프트 주입, ② 고손실 trial Loki timeout 대비 read timeout 상향·재시도, ③ F11/F12 별도 시점 수집을 1차 배치와 동일 조건으로 재정렬(교란 제거).

P4. validator 효과 분리 (현재 측정 불가)
- 근거(데이터): V9 validator가 corrected 4건·skipped 2건 동작하지만, validator on/off 비교 arm이 없어 효과를 정량화할 수 없다. validator는 A·B 양쪽에 동일 적용되어 독립변수도 아님.
- 개선: validator on/off A/B test로 "잔류 fault 정정이 정확도에 주는 순효과"를 별도 측정.

P5. 모델·기법 상향 검토 (단, 모델 고정 제약 내에서)
- 근거(논문): 우리 43% vs Flow-of-Action 64%(GPT-4-Turbo)·SynergyRCA ~0.90(graph+verifier). gpt-4o-mini 고정은 유지하되, 프레임워크 레벨에서 topology/graph 컨텍스트(SynergyRCA), hypothesize-then-verify(SpecRCA), ReAct식 도구 호출(Flow-of-Action)을 B에 추가하는 것이 정확도 천장을 올릴 후보.

## 5. 결론 · 한계

가설(B>A) 성패 판정: 미입증(방향만 지지). B 43.1% vs A 34.5%(+8.6%p)는 방향상 가설과 일치하나, McNemar/정확검정 p=0.267로 유의하지 않고, 채점 임계 0.6에서 역전되어 robust하지 않다. 우위의 대부분은 node-level 단일 fault(F4)에서 나오며, 네트워크 fault의 유일한 B 정답은 채점 노이즈다. 현 상태로는 "GitOps+RAG가 LLM RCA 정확도를 높인다"는 논문 주장을 뒷받침할 수 없다.

일반화 한계: 단일 클러스터·단일 앱·단일 모델·trial당 1회. 절대 정확도(34~43%)가 선행연구 상위(64%, 0.90)에 크게 못 미쳐 외적 타당성 약함.

수집 한계 (고강도 trial 신호 품질):
- F11/F12는 1차 배치와 다른 시점·일부 다른 조건에서 재수집됨(교란).
- 고손실 trial에서 Loki read timeout 2건으로 로그 신호 부분 누락, tc del 15초 타임아웃 3건으로 잔류 fault가 300s 안전망으로만 정리 — 다음 trial 오염 가능성을 validator가 커버하지 못함(설계상 노드 레벨 사각지대).

re-baseline으로서의 평가: 데이터 파이프라인·validator·무결성은 정상 동작했다(skip 처리·분모 제외 정확). 그러나 결과의 신호 대 잡음비가 낮아, 다음 라운드(V2.2)는 P1(채점 robustness)·P2(처치 분해)를 먼저 해결한 뒤에 가설 검증으로 진입해야 한다.

## 부록 — 인용한 선행연구
| 출처 | 위치 | 정량 수치 | 핵심 기법 | 신뢰도 |
|---|---|---|---|---|
| Flow-of-Action (WWW 2025, arXiv 2502.08224) | docs/papers/flow-of-action.md | GPT-4-Turbo 64.0%; SOP 제거 −38.67pp; CoT 32.6/ReAct 35.5/K8SGPT 11.1 | MAS+SOP+Action Set | HIGH(1차 독해) |
| ReAct (ICLR 2023, arXiv 2210.03629) | 위키 concepts/ReAct 프레임워크.md | 35.5% | Thought-Action-Observation | HIGH |
| SynergyRCA (arXiv 2506.02490) | 위키 concepts/LLM 기반 RCA.md 경유 | precision ~0.90 (K8s) | StateGraph+StateChecker | MEDIUM(원논문 표 1차 미확인) |
| Auditable Graph-Guided RCA (arXiv 2606.08590) | 위키 sources/2026-06-20-auditable-graph-guided-rca-검증-아이디어.md | 방법론(claim-audit 4단계) | typed evidence graph | MEDIUM |
| SpecRCA(2601.02736)·eARCO·COCA·mABC 등 | 위키 RCA 계보 | 수치 없음(날조 안 함) | hypothesize-verify/RAG/voting | LOW |

신뢰도 주: Flow-of-Action·ReAct는 1차 자료로 직접 확인. SynergyRCA·Auditable-RCA 수치는 위키 페이지 기록 인용이며 원논문 표는 1차 미확인(확인 불가 → MEDIUM). repo에 paper_survey_v*.md는 존재하지 않으며 deep_analysis_v5/v8/v9.md만 존재.
