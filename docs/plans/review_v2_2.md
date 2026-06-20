# V2.2 계획 비평 (Step 2 — plan critique 5축 + 사전 검정력)

> 작성: 2026-06-20 · 입력: experiment_plan_v2_2.md, analysis_v2_1.md, deep_analysis_v2_2.md + 코드 실측
> 리뷰어: 맥락 분리된 독립 시각(general-purpose sub-agent) + 오케스트레이터 검정력 시뮬레이션
> 판정 한 줄: **방향·기법은 견고하나, §2가 "핵심"이라 부른 "C4>C5>C1" 게이트에 대응하는 통계가 §4에 없고, 현 표본으로는 그 게이트가 구조적으로 거의 안 열린다(검정력 계산 확증). 코딩 전 P0 6건 해소 필요.**

## 1. 사전 검정력 시뮬레이션 (P0-H — 14h 정당화의 결정 게이트)

Monte Carlo McNemar(paired binary, 4000 reps), V2.1 관측 효과 기반:

| 비교 | 효과 가정 | trial=5 (n=60) | trial=7 | trial=10 | trial=15 |
|---|---|---|---|---|---|
| C4 vs C1 (관측효과 disc=.224/split=.69) | V2.1 실측 | **0.20** | 0.30 | 0.43 | — |
| C4 vs C1 (낙관 disc=.30/split=.75) | 큰 효과 | 0.49 | 0.66 | **0.83** | 0.96 |
| **C4 vs C5 (내용 > 길이)** | 작은 효과 disc=.18/split=.65 | **0.09** | — | 0.22 | 0.33 (t=20: 0.46) |

**결론(치명):**
- "내용의 순기여"를 입증하는 **C4 vs C5 게이트는 trial=5에서 검정력 0.09, trial=20에서도 0.46** — 어떤 현실적 trial 수로도 유의 도달 불가.
- 병목은 **측정 노이즈(k)가 아니라 표본 수(trial)**. k=5→3으로 줄여도 검정력 거의 불변, 대신 trial 증량이 유일하게 검정력을 올림.
- 즉 **현 설계로 14h를 돌리면 V2.1과 같은 "비유의"로 끝날 구조적 위험이 크다.** → 게이트를 "유의성 승리"가 아닌 **"효과크기 추정 + 정직한 검정력 보고"**로 재정의해야 한다(아래 P0-G, 사용자 결정 사항).

## 2. Plan critique 5축

### ① 구성 타당성
- **(P0-A 치명) factorial 안의 길이 교락 부활.** placebo(C5)는 C4 총길이만 통제. 그러나 C1<C2(+GitOps)≠C3(+RAG)<C4로 셀마다 길이가 달라, `GitOps main=(C2+C4)−(C1+C3)`에 GitOps 내용효과 + (C2 vs C3) 길이차가 섞인다. V2.1 결함 #4가 factorial 내부에서 부활. → **수정: GitOps 블록·RAG 블록 토큰을 설계 단계에서 동일화(T_block로 pad/truncate)** 해 두 main effect를 같은 길이 baseline 위에서 비교.
- **(P0-B) 대표 score 규칙 부재.** k=5 다수결 라벨의 대표 correctness_score 산출 규칙 미정 → 임계 sweep 입력 모호. → **수정: 최빈 라벨 샘플들의 중앙값**을 대표값으로, CSV 별도 컬럼.

### ② 내적 타당성
- **(P1-C) 저품질 trial 처리 부재.** Loki timeout 등으로 신호 결손된 trial은 5 arm 전부 결손 공유 — 공정하나 처치 측정 불가. → **수정: 신호수집 단계 저품질 플래그 + 포함/제외 sensitivity.**
- **(P1-D) seed 실효성·채점 tie-break.** OpenAI seed는 best-effort(system_fingerprint 변동 시 무효). 채점 m=3 tie-break 규칙 생성쪽만 명시. → **수정: 채점 결정적 tie-break(score 중앙값) + system_fingerprint 로깅.**
- **(P1-E) RAG↔GitOps 중복이 구호.** 측정·조치 절차 없음. → **수정: 토큰/엔티티 Jaccard 정량화 dry-run 출력, 임계 초과 시 런북 재작성.**

### ③ 외적 타당성
- 단일 클러스터·앱·모델·trial=5 한계를 상속하나 명문화 안 됨. trial=5는 fault별 정확률이 6단계로만 양자화돼 셀 추정 해상도 거침. → **(P2-F) 결론 일반화 범위 절 사전 추가 + 효과크기·CI를 1차 지표로.**

### ④ 통계 타당성
- **(P0-G 치명) 게이트 통계 부재.** Cochran Q는 omnibus(모두 같다)만, post-hoc McNemar는 개별 쌍만 — **순서(C4>C5>C1) 검정 통계량이 없다.** → **수정: GLMM 1차** `correct ~ GitOps*RAG + (1|fault)`(binomial)로 계수 직접 검정, "내용 순기여" = (GitOps 또는 RAG 주효과>0 유의) AND (placebo 대비 both 추가효과>0). 순서 필요 시 closed/step-down(C4vsC1→C4vsC5→C5vsC1). McNemar는 보조 강등.
- **(P0-H) 사전 power §1.** 검출력 낮음 확인 → 게이트를 추정 중심으로 재정의(사용자 결정).
- **(P1) 임계 sweep 다중성.** primary 임계 1개(0.5) 사전 등록, 0.6/0.7은 보정 없는 robustness 분리.

### ⑤ 대안 가설
- **(P0-I) judge 동방향 편향.** 같은 gpt-4o-mini judge 3콜은 독립 아닌 상관 오류 3복제. self-preference로 "GitOps 언급 답"에 후하면 C4 부풀림 — 다수결로 못 잡음. → **수정: judge blinding(채점 입력에서 arm 식별·출처 단서 제거). 무료 완화.**
- **(P1) fault별 효과 이질성.** V2.1 B 우위 대부분이 F4 단일. → fault별 forest plot 필수 산출물화.
- **(P1) placebo 신호 누출.** 다른 fault 실제 diff 금지 → 무의미 보일러플레이트.

## 3. 비용 14h 재판정
cooldown ~6h는 arm/k 무관 고정. LLM ~8h는 병렬화 가능. **k=5→3은 검정력 거의 불변하므로 비용만 절약** → k=3 권장, 절약분은 (필요 시) trial 증량에. **단 placebo·factorial은 본 실험의 독창 통제축이므로 유지.**

## 4. 코딩 전 우선순위
**P0(필수):** A 길이직교화 · B 대표score규칙 · G 게이트 GLMM 재정의 · H 사전power(완료, §1) · I judge blinding · **+ 게이트 추정 재프레이밍(사용자 결정)**.
**P1(권장):** C 저품질trial플래그 · D tie-break+fingerprint · E 중복Jaccard · placebo 보일러플레이트화 · primary임계 고정 · fault별 forest plot.
**P2(선택):** F 일반화범위절 · 효과크기 1차승격 · 약fault 적응샘플링.

## 5. 미해결 — 사용자 결정 필요
§1 검정력이 보여주듯 "유의성 승리"는 구조적으로 어렵다. V2.2의 기여를 **(a) 추정 중심 재프레이밍**(효과크기+CI+정직한 검정력 보고)으로 갈지, **(b) trial 대폭 증량**(비용↑, 그래도 C4>C5는 미달)으로 갈지, **(c) 원안 유지**(유의성 게이트, 비유의 종료 위험 감수)할지는 논문 주장 범위와 직결 → 사용자 확정 후 P0 적용·코딩.
