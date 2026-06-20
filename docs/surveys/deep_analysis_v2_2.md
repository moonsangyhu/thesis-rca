# 심층 분석: V2.2 실험 설계를 위한 개선점 도출 (Step 0.5)

> 분석일: 2026-06-20
> 분석 대상: V2.1 결과(results/analysis_v2_1.md, experiment_results_v2_1.csv) + V2.1 하네스(experiments/v2_1/)
> 목적: V2.1 비판에서 확정된 **P1(측정 robustness)·P2(처치 분해)**의 *구현 기법*을 데이터·문헌 근거로 구체화하여 V2.2 brainstorming(Step 1) 입력 확보
> 범위 한정: 데이터 통계 분석은 `analysis_v2_1.md`(독립 분석가가 .venv python으로 직접 계산)에 이미 충실하므로 **재계산하지 않고 인용**한다. 본 문서는 그 위에서 "어떻게 고칠지"에 집중한다.

## 0. 출발점 — V2.1이 남긴 결함 (analysis_v2_1.md 인용)

| # | 결함 | 근거 수치 | V2.2 처치 |
|---|---|---|---|
| 1 | B>A 통계 미입증 | McNemar χ²(cc)=1.23, exact p=0.267, discordant n=13 | P1: 반복측정·검정력 보강 |
| 2 | **채점 임계 0.5 인공물** | 0.5→B 43.1%/A 34.5%, **0.6→A 25.9%/B 22.4% 역전**. B 정답 25개 중 12개(48%)가 정확히 0.5 | P1: 임계 sweep 병기 + 다수결 |
| 3 | 채점 비결정성 | F12 t2 동일 답을 A=0.1/B=0.5로 갈라 채점 | P1: judge 다중콜+seed+reference |
| 4 | 묶음 처치 + 길이 교락 | 독립변수 "GitOps ∪ RAG", B prompt 토큰 +38% | P2: 2×2 factorial + placebo |
| 5 | 단일 측정 | trial당 1회, 분포 없음 | P1: k회 반복 샘플 |

→ 결론(analysis_v2_1 §5 재확인): **가설 재검증 이전에 "측정 자체"를 고친다.** V2.2 = P1+P2. (P3 네트워크 신호·P4 validator는 V2.3로 분리 — goal 문서 §2 합의.)

## 1. V2.1 하네스 구현 지점 지도 (파생 대상)

V2.2는 `experiments/v2_1/`를 파생한다. 구현 삽입 지점(Explore 매핑):

| 개선 | 파일:라인 | 현재 상태 → 변경 |
|---|---|---|
| P1-1 k회 반복 샘플 | `experiments/shared/runner.py:139-157` | `engine.analyze()` 1회 → **k회 루프 후 다수결 집계** |
| P1-2 채점 다수결 | `experiments/shared/llm_client.py:83-114` `judge_correctness()` | 1콜 → **m콜 다수결** |
| P1-3 seed/temp 고정 | `experiments/shared/llm_client.py:30-69` `call_llm()` | temperature·seed 파라미터 **없음** → 인자 추가 |
| P1-4 임계 sweep | `llm_client.py:109` `correct = 1 if score>=0.5 else 0` | 단일 0.5 이진화 → **score 보존 + 0.5/0.6/0.7 사후 sweep** |
| P2 arm 분기 | `runner.py:120-157` + `src/processor/context_builder.py:47-115` | System A/B 2분기 → **A / +GitOps / +RAG / +both / placebo 5-arm** |

핵심 구조 사실(비용에 결정적): **fault injection·신호수집은 (fault,trial)당 1회**(runner.py Step1-5), 모든 arm은 그 *동일 신호*를 공유하고 컨텍스트 구성+LLM 호출만 다르다. → **arm 추가는 cluster cooldown을 늘리지 않고 LLM 호출만 늘린다**(placebo arm이 저렴한 이유). 모델: `gpt-4o-mini` 고정(`--provider openai --model gpt-4o-mini`), 키 `OPENAI_API_KEY`(현재 미설정 — Step 4 직전 필요).

## 2. P1 측정 robustness — 기법 확정 (문헌 근거)

### 2-1. Self-consistency 다중 샘플 (생성)
| 기법 | 출처 | 정량 | 우리 적용 |
|---|---|---|---|
| Self-Consistency | Wang et al. ICLR 2023, arXiv:2203.11171 | CoT 대비 GSM8K +17.9%p 등, 권장 T=0.7 | trial당 1회 → **k 샘플 다수결** |
| RCA 도메인 적용 | RCAgent, Alibaba arXiv:2310.16340 | RCA 지표 일관 향상, **k≈20 saturation** (sampling T 미확인) | RCA에서도 효과 입증됨 |
| 한계효용 급감 | arXiv:2511.00751 (2025) | 현대 모델 k=15 균형, 고샘플 구간 하락 | **k=5가 비용/이득 균형점** |

**확정:** 생성을 **k=5 self-consistency 다수결, T=0.7**. (선택지: 비용 민감하면 k=3 먼저, fault type별 차등효과 분석.) 다수결 단위 = `identified_fault_type`(이산 라벨) 최빈값.

### 2-2. LLM-judge 비결정성·인플레이션 완화 (채점)
| 기법 | 출처 | 정량 | 적용 |
|---|---|---|---|
| temp=0도 비결정 잔존 | arXiv:2503.09347 (2025) | GPT-4T ≈5.7% 투표 변동 | seed/temp=0만으론 불충분 → **다수결 병행 필수** |
| Position-swap | Zheng et al. NeurIPS 2023, arXiv:2306.05685 | 순서로 ⅓ 뒤집힘, swap으로 일관성 65→77.5% | 우리 judge는 pairwise 아님(단일 답 채점) → **해당 약함**, reference rubric 우선 |
| Reference-guided | 동 arXiv:2306.05685 | 추론 실패율 70→15% | **ground_truth를 judge 프롬프트에 명시**(이미 일부 적용) |
| 점수 인플레이션/self-preference | Panickssery et al. arXiv:2410.21819 | judge가 자기 출력 10–25% 더 선호 | **cross-model judge**(채점≠gpt-4o-mini) 검토 — 단 모델고정 제약과 충돌, brainstorming서 결정 |
| Judge 다수결 | self-consistency 계열(1차 ID 미확인) | +4%p, 3표부터 안정 | **m=3~5 다수결** |

**확정:** 채점기 = **temp≈0 + seed 고정 + reference rubric + m=3 다수결**. correctness_score는 **이진화하지 않고 원점수 보존**해 CSV 기록 → 사후 임계 sweep. (cross-model judge는 "모델 gpt-4o-mini 고정" 가드레일과 긴장 → brainstorming HARD-GATE에서 사용자 결정.)

### 2-3. 통계 — 반복측정 올바르게 반영
analysis_v2_1의 McNemar는 (fault,trial) 쌍을 독립 취급. **반복측정(5 trials/fault)을 60 독립건으로 넣으면 거짓 정밀도(과소 p)** 위험.
| 방법 | 출처 | 용도 |
|---|---|---|
| 임계 sweep + 신뢰구간 | sklearn/관행 | 단일 cutoff 금지, 0.5/0.6/0.7 전부 병기 |
| exact binomial McNemar | Edwards 1948 | discordant b+c<25면 exact (우리 n=13 → exact 필수) |
| Cohen's h | Cohen 1988 | paired 비율차 효과크기 (small .2/med .5/large .8) |
| Newcombe hybrid score CI | Newcombe 1998 | paired 비율차 신뢰구간 |
| GLMM (item random effect) | lme4 | 반복측정 정석 — fault를 random effect |
| Cochran's Q + post-hoc | Cochran 1950 | **3+ arm(우리 5-arm) omnibus** → post-hoc McNemar + Bonferroni |

**확정:** ① 1차 = **fault당 정확률 집계 후(12 item) 비교 + GLMM** 정석, ② arm 다중비교는 **Cochran's Q → post-hoc McNemar(Bonferroni)**, ③ **임계 sweep·Cohen's h·Newcombe CI 항상 병기**, ④ 검정력 부족 시 "비유의 ≠ 효과 없음" 명시. (rule-of-thumb 경계값은 휴리스틱임을 보고서에 주석.)

## 3. P2 처치 분해 — 2×2 factorial + placebo (문헌 근거)

### 3-1. Factorial 설계
| 근거 | 출처 | 시사점 |
|---|---|---|
| OFAT vs Factorial | Czitrom, Am.Statistician 1999 | A→B 단일 점프는 main effect만, interaction 못 봄 |
| Hidden replication | Czitrom 1999; Montgomery 2020 | 같은 run 수로 더 강한 검정력(셀 합산 추정) |
| 시너지 사례 | AgenticRAG arXiv:2510.02668, SRAG arXiv:2603.26670 | 컴포넌트 결합 시 super-additive — interaction에서 개선 옴 |
| 선행연구 ablation | Flow-of-Action(docs/papers/flow-of-action.md) | SOP 제거 −38.67pp 분리측정 — 우리도 컴포넌트 분리 필요 |

**확정 — 4셀 2×2(GitOps × RAG):**
- C1 = A(baseline) / C2 = A+GitOps / C3 = A+RAG / C4 = A+GitOps+RAG(=기존 B)
- GitOps main = (C2+C4)−(C1+C3) / RAG main = (C3+C4)−(C1+C2) / interaction = (C4−C2)−(C3−C1)
- **confound 점검:** RAG 런북이 GitOps 정보를 중복 회수하지 않도록 두 소스 분리(중복 시 main effect 상호 마스킹).
- **검정력 경고:** trial=5는 interaction 검정에 약할 수 있음 → 사전 power 인식하고 결과에 명시.

### 3-2. 길이 교락 통제 — placebo arm (핵심)
analysis_v2_1 대안가설 (b): "B의 +38% 토큰이 단지 더 많은 단서를 줘서일 수 있음(내용 무관)".
| 근거 | 출처 | 정량 |
|---|---|---|
| 무관 컨텍스트가 성능 저하 | Shi et al. ICML 2023, arXiv:2302.00093 (GSM-IC) | CoT 80.8→72.4% (−8.4%p) |
| Lost in the Middle | Liu et al. TACL 2024, arXiv:2307.03172 | 중간 위치 ~20%p 하락 |
| **Power of Noise (역설)** | Cuconasu et al. SIGIR 2024, arXiv:2401.14887 | **랜덤 무관 문서 추가가 정확도 최대 ~35% 향상** |
| Context Rot | Chroma 2025 | 길이만 늘려도 체계적 하락 — placebo 설계 템플릿 |

**확정 — placebo arm(C5) 추가:** A + (C4와 토큰 수 matched된 **무관 filler 텍스트**: 다른 장애의 GitOps diff/셔플 로그 등).
- 판정 규칙: **C4(both) > C5(placebo) > C1(baseline)** 가 유의해야 "GitOps+RAG **내용**의 순기여" 주장 가능.
- C5도 baseline보다 오르면 → 개선의 일부/전부는 **토큰 증가 효과**(Power of Noise 함정)임을 폭로.
- 삽입 위치(시작/중간/끝)도 통제(Lost in the Middle).

## 4. 개선 가설 (V2.2 — 우선순위)

### 가설 P1 (최우선): 측정 robustness 하네스
- **변경**: 생성 k=5 self-consistency(T=0.7) + 채점 m=3 다수결(temp≈0/seed/reference) + correctness_score 원점수 보존 + 임계 sweep(0.5/0.6/0.7) + 통계(exact McNemar·Cohen's h·Newcombe CI, fault 집계/GLMM).
- **근거(데이터)**: 결함 #2·#3·#5 — 결론이 0.5 임계와 단일측정·채점노이즈에 좌우.
- **근거(문헌)**: arXiv:2203.11171, 2310.16340(RCAgent), 2503.09347, 2306.05685.
- **메커니즘**: 단일 측정 → 분포로 바꿔 채점 노이즈 평균화 + 임계 의존성 노출.
- **구현 범위**: `llm_client.py`(seed/temp, judge 다수결), `runner.py`(k 루프), `config.py`(CSV에 score 분포·임계별 컬럼), 분석 스크립트 신규.
- **리스크**: LLM 호출 4~7배 증가(§5 비용). 완화: arm은 동일 신호 공유, LLM 호출 병렬화.

### 가설 P2 (동시 적용): 2×2 factorial + placebo
- **변경**: System A/B 2-arm → **5-arm**(A/+GitOps/+RAG/+both/placebo). main·interaction 분해.
- **근거(데이터)**: 결함 #4 — 묶음 처치+길이 교락. 대안가설 (b)(c) 미배제.
- **근거(문헌)**: Czitrom 1999, Flow-of-Action(−38.67pp), arXiv:2302.00093·2401.14887(placebo 근거).
- **메커니즘**: GitOps·RAG·길이 효과를 직교 분리.
- **구현 범위**: `context_builder.py` arm 토글 + placebo filler 생성기, `runner.py` arm 루프.
- **리스크**: arm당 trial=5는 interaction 검정력 약함 → 명시. RAG↔GitOps 정보 중복 시 마스킹 → 소스 분리.

> P1·P2는 **독립 변경이지만 한 하네스에 동시 구현**(arm 루프 안에 k 루프). 둘 다 "측정/설계 인프라"여서 분리 실행 이득 없음. brainstorming에서 확정.

## 5. 비용 타당성 (Python 계산)

(fault,trial) 신호수집 1회는 arm과 무관, cooldown ~6h 고정. LLM 호출만 arm×k×judge로 증가:

| 구성 | LLM 호출 | 직렬 wall-clock(추정) |
|---|---|---|
| V2.1 (2-arm, k1, m1) | 420 | 기준 |
| 5-arm, k3, m3 | 2,250 | ~6.2h LLM + ~6h cooldown ≈ **12h** |
| 5-arm, k5, m3 | 2,850 | ~7.9h LLM + ~6h ≈ **14h** |
| 4-arm(placebo 제외), k5, m3 | 2,280 | ~12h |

→ **k=5·m=3·5-arm ≈ 2,850콜/14h** 오버나잇 1회로 feasible. LLM 호출은 arm/샘플 독립 → **병렬화로 LLM wall-clock 대폭 단축 가능**. 비용 민감 시 **k=3 먼저, placebo는 고정 유지**.

## 6. 요약 및 권장 우선순위 (brainstorming 입력)

1. **P1+P2 동시**가 본 라운드. P3(네트워크 신호)·P4(validator)는 V2.3로 분리(goal §2 합의).
2. **brainstorming(Step 1) HARD-GATE 확정 필요 항목** (5문항 cap):
   - (a) arm 수: **5(2×2+placebo)** 권장 vs 4 vs 3.
   - (b) k(생성 샘플): **5** 권장 vs 3(비용↓).
   - (c) judge: m=3 다수결+reference 확정. **cross-model judge 허용?**(모델고정 가드레일과 긴장).
   - (d) fault 범위: **F1–F12 전체**(F11/F12 신호보강은 P3로 미루되 수집은 유지) vs F1–F10.
   - (e) 통계 1차: **fault 집계 후 exact McNemar + Cohen's h/CI + 임계 sweep**(GLMM 보조).
3. 권장 기본안: **5-arm · k=5 · judge m=3(동일 모델, reference rubric) · F1–F12 · score 원점수 보존 + 임계 sweep**.

## 부록 — 인용 문헌
| 출처 | arXiv/연도 | 정량 | 신뢰도 |
|---|---|---|---|
| Self-Consistency (Wang) | 2203.11171, ICLR2023 | GSM8K +17.9%p, T=0.7 | HIGH |
| RCAgent (Alibaba) | 2310.16340 | k≈20 saturation(RCA) | MEDIUM(T 미확인) |
| SC scaling 한계 | 2511.00751, 2025 | k=15 균형 | MEDIUM |
| LLM-judge 비결정 | 2503.09347, 2025 | GPT-4T 5.7% 변동 | MEDIUM |
| MT-Bench/judge | 2306.05685, NeurIPS2023 | swap 65→77.5%, ref 70→15% | HIGH |
| Self-preference | 2410.21819, 2024 | 10–25% 자기선호 | MEDIUM |
| OFAT vs Factorial | Czitrom 1999 | 방법론 | HIGH |
| Irrelevant Context | 2302.00093, ICML2023 | −8.4%p | HIGH |
| Power of Noise | 2401.14887, SIGIR2024 | +~35%(역설) | MEDIUM |
| Lost in Middle | 2307.03172, TACL2024 | ~20%p | HIGH |
| Flow-of-Action | docs/papers/flow-of-action.md | −38.67pp ablation | HIGH(1차) |

> 미확인 주: RCAgent sampling T, judge 다수결 1차 arXiv ID·정확 수치, Power-of-Noise related>random 정확 비교는 원문 PDF 재확인 권장(본문 표 직접 대조 미수행).
