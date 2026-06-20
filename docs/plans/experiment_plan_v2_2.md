# 실험 계획서 V2.2 — 측정 신뢰성 + 처치 분해 (rev2, 비평 반영)

> 작성: 2026-06-20 (Step 1 brainstorming) · 개정: Step 2 plan critique(review_v2_2.md) + 사전 검정력 반영
> 입력: results/analysis_v2_1.md, docs/surveys/deep_analysis_v2_2.md, docs/plans/review_v2_2.md
> 설계 확정(사용자 승인): **5-arm · 생성 k=3 · 동일 gpt-4o-mini judge(m=3, blinded) · F1–F12 · 추정 중심 프레이밍**
> 모델 `gpt-4o-mini` 고정. 개선은 프레임워크 레벨에서만.

## 0. 프레이밍 — 추정 중심 (검정력 반영, 사용자 결정)

사전 검정력(review_v2_2.md §1): C4 vs C1 power=0.20(trial=5), **C4 vs C5(내용>길이) power=0.09** — 유의성 승리는 구조적으로 불가. 병목은 측정노이즈(k)가 아니라 표본수(trial).

→ **V2.2 기여를 "유의성 입증"이 아니라 "편향 없는 robust 측정 + 효과 분리 추정 + 정직한 검정력 보고"로 재정의.** 1차 지표 = **효과크기(Cohen's h) + 신뢰구간(Newcombe CI) + GLMM 계수**. 유의성(McNemar/GLMM p)은 **보조·robustness**로 보고하되 성공 게이트로 쓰지 않는다. 절대 정확도·임계 sweep·arm 분해를 정확히 추정해 "GitOps·RAG·길이 효과의 크기와 방향"을 CI와 함께 제시하는 것이 목표.

## 1. 가설 (추정형)

> **H(추정):** A 대비 GitOps·RAG 처치의 정확도 효과크기를 길이 효과와 분리해 추정하면, 그 점추정·CI가 (a) 양의 방향이고 (b) placebo(길이만) 효과를 초과하는지를 측정한다. 결론은 채점 임계값·샘플링 노이즈에 robust해야 한다.

V2.1은 "B(GitOps∪RAG)>A"를 방향만 지지(p=0.267)하고 ① 임계 0.5 인공물(0.6 역전), ② 묶음+토큰 +38% 길이 교락, ③ 채점 비결정성, ④ 단일 측정으로 미입증. V2.2는 측정·설계 자체를 고쳐 **효과를 정직하게 추정**한다.

## 2. 독립변수 — 5-arm 처치 구조 (P2)

(fault,trial)당 fault injection·신호 수집 1회, 5 arm이 **동일 신호** 공유(arm은 cooldown 불변, LLM 호출만 증가).

| arm | 컨텍스트 | 역할 |
|---|---|---|
| `C1_A` | observability only (kubectl+Prom+Loki) | baseline |
| `C2_gitops` | A + GitOps 블록 | GitOps main effect |
| `C3_rag` | A + RAG 런북 블록 | RAG main effect |
| `C4_both` | A + GitOps + RAG (=기존 B) | full/interaction |
| `C5_placebo` | A + **무의미 보일러플레이트(C4 추가분과 토큰 매칭)** | 길이 교락 통제 |

### 2-1. 길이 직교화 (P0-A — 비평 치명결함 수정)
placebo가 C4 총길이만 통제하면 main effect 안의 길이차(C2≠C3)가 남는다. → **GitOps 블록·RAG 블록을 동일 토큰 예산 `T_block`으로 pad/truncate** 해 C2·C3의 추가 길이를 같게 맞춘다. C5 placebo는 `2·T_block`(=C4 추가분)을 무의미 텍스트로 채운다. 모든 arm 동일 위치/순서 삽입(Lost in the Middle 통제).

### 2-2. placebo 설계 (P1 — 신호 누출 차단)
filler = **무의미 보일러플레이트/셔플된 자연어**(다른 fault의 실제 GitOps diff 금지 — 라벨 공간 오염 방지). 토큰만 `2·T_block` 매칭, 의미 신호 0.

### 2-3. 분해·게이트 (추정형)
- GitOps main = (C2+C4)−(C1+C3), RAG main = (C3+C4)−(C1+C2), interaction = (C4−C2)−(C3−C1).
- **판정(추정 게이트):** GLMM 계수로 ① GitOps 또는 RAG 주효과 점추정>0 (CI 보고), ② **both 대비 placebo 추가효과(C4−C5) 점추정>0** 이면 "내용의 순기여 방향 지지". 유의성은 보조 표기.
- **Confound 통제:** RAG 런북↔GitOps 정보 중복을 Jaccard로 정량화(§3-5), 임계 초과 시 런북 재작성.

## 3. 측정 robustness (P1)

### 3-1. 생성 — self-consistency k=3
- 각 arm을 `temperature=0.7`로 **k=3 샘플**. (검정력상 k는 병목 아님 → k=3로 비용 절감, 측정노이즈는 대부분 완화.)
- 다수결 단위 = `identified_fault_type` 최빈값. 동률 시 첫 샘플(결정적 tie-break).
- 3샘플 각각의 라벨·score·confidence를 raw JSON 보존(분포 분석).

### 3-2. 대표 correctness_score (P0-B 수정)
- 다수결 라벨에 속한 샘플들의 **correctness_score 중앙값**을 대표값으로 채택. CSV 별도 컬럼(`rep_correctness_score`)에 기록. 임계 sweep의 입력 = 이 대표값.

### 3-3. 채점 — judge 다수결 m=3 + blinding (P0-I 수정)
- 동일 `gpt-4o-mini` judge, `temperature=0 + seed 고정 + reference rubric(ground_truth 제공)`.
- **judge blinding:** 채점 입력에서 **arm 식별·출처 단서 제거**(진단 라벨+근거만 전달, 어느 arm/컨텍스트에서 나왔는지 숨김) — self-preference·동방향 편향 완화.
- **m=3 다수결**, 채점 tie-break = score 중앙값(P1-D, 결정적). `system_fingerprint` 로깅(seed 무효 사후 식별).

### 3-4. 점수 보존 + 임계 sweep
- correctness 원점수·분포 전부 보존, 이진화는 사후. **primary 임계 = 0.5 사전 등록**, 0.6/0.7은 보정 없는 robustness check로 분리 보고(다중성 폭발 방지).

### 3-5. 저품질 trial 플래그 + 중복 점검 (P1-C, P1-E)
- 신호 수집 단계에서 **저품질 플래그**(Loki timeout/빈 로그/recovery 잔류) 기록 → 분석에서 포함/제외 sensitivity 양쪽 보고.
- RAG 런북↔GitOps 컨텍스트 **토큰 Jaccard** dry-run 출력. 임계(예: 0.3) 초과 시 런북 재작성.

## 4. 통계 분석 (Step 5 독립 분석가)

1. **1차 = GLMM** (P0-G): `correct ~ GitOps * RAG + (1|fault)` (binomial). GitOps·RAG·interaction 계수와 CI 직접 추정. placebo는 `length` 항/별도 대비(C4−C5)로.
2. **효과크기·CI 1차 승격** (P2): 모든 arm 쌍에 **Cohen's h + Newcombe hybrid score CI**를 점추정과 함께.
3. **보조 유의성:** fault 집계(12 item) exact binomial McNemar, 다중 arm은 Cochran Q → post-hoc(Bonferroni). **검정력 사전 보고(§review_v2_2 §1) 병기, "비유의 ≠ 효과 없음" 명시.**
4. **임계 sweep(0.5 primary / 0.6·0.7 robustness)** 전부 병기.
5. **fault별 효과 forest plot**(P1) 필수 산출 — F4식 단일 fault 편중 노출.
6. 경계값(b+c<25, Cohen band)은 휴리스틱 주석.

## 5. 구현 설계 (experiments/v2_2/, v2_1 파생)

| 파일 | 변경 |
|---|---|
| `experiments/shared/llm_client.py` | `call_llm()`에 `temperature`·`seed` 인자; `judge_correctness_voted(m=3, blinded)` 다수결·중앙값 tie-break·fingerprint 반환 |
| `experiments/shared/runner.py` | 신호수집 1회 → **5-arm 루프 × 생성 k=3 루프**; 다수결 라벨+대표score 집계; 저품질 플래그 |
| `src/processor/context_builder.py` | arm 토글(C1~C5) + **블록 토큰 동일화(T_block pad/truncate)** + placebo 보일러플레이트 생성기 + Jaccard 중복 계산 |
| `experiments/v2_2/config.py` | CSV에 `arm`, `gen_samples_json`(k=3), `correctness_scores_json`(m=3), `rep_correctness_score`, `correct@0.5/0.6/0.7`, `low_quality_flag`, `system_fingerprint`, `gitops_rag_jaccard` |
| `experiments/v2_2/run.py` | v2_1 파생, version=v2_2, arm/k/m CLI |
| `experiments/v2_2/analyze_v2_2.py` (신규) | §4 통계(GLMM·Cohen's h·Newcombe CI·McNemar·Cochran Q·임계 sweep·factorial 분해·forest plot) |

**검증:** `--dry-run`(mock 신호)으로 5-arm×k=3×m=3 루프·CSV 스키마·집계·길이직교화·Jaccard·blinding end-to-end 확인 후에만 실 수집.

## 6. 종속변수·기록
- **1차:** arm별 정확도 점추정 + CI(임계 0.5/0.6/0.7), GLMM 계수, Cohen's h.
- **부:** 생성 다수결 일치율(k=3), judge 다수결 일치율(m=3), confidence 보정, latency·토큰, low_quality 비율, Jaccard.
- CSV `results/experiment_results_v2_2.csv`, raw `results/raw_v2_2/`(arm별 3샘플+3채점 분포 보존).

## 7. 규모·실행
- 12 fault × 5 trial × 5 arm × (k=3 생성 + m=3 채점) ≈ **5·60·7.5 ≈ 2,250 LLM 호출**. 직렬 ~12h(cooldown ~6h 고정 포함). arm/샘플 독립 → 병렬화로 LLM wall-clock 단축.
- Step 4: `/lab-tunnel` → `nohup` → `/experiment-status`(~10분 보고) → `/lab-restore`.
- ⚠️ 전제: `OPENAI_API_KEY` 설정(현재 미설정), 랩 터널 GREEN(2026-06-19 Preflight 달성).

## 8. 외적 타당성 — 결론 일반화 범위 (P2-F, 사전 선언)
단일 클러스터(KT Cloud Debian 6노드, Cilium)·단일 앱(Online Boutique)·단일 모델(gpt-4o-mini)·GitOps/RAG **구현 1종**·trial=5에 한정. 다른 런북 품질·다른 GitOps 도구·다른 토폴로지로 일반화 불가. trial=5는 fault별 정확률을 6단계로 양자화 → 점추정보다 효과크기·CI를 1차 해석.

## 9. 가드레일·격리
- 모델 `gpt-4o-mini` 고정. 개선은 프레임워크(반복·ablation·채점) 레벨만.
- 기존 CSV/raw/ground_truth 불변. `experiments/v2_2/`·`results/*_v2_2.*` 격리.
- main 직접 커밋·push·force·--no-verify·--admin 금지. feature `exp/v2_2-measurement-ablation` → 한글 PR → rebase 머지.

## 10. Definition of Done
1. P1 하네스(k=3 생성 + m=3 blinded 채점 다수결 + seed/fingerprint + 대표score + 임계 sweep + 저품질 플래그) 구현·--dry-run 검증.
2. P2 5-arm(C1~C5, 블록 토큰 직교화 + placebo 보일러플레이트 + Jaccard) 구현·수집.
3. 독립 비판 분석가가 `results/analysis_v2_2.md` 작성(GLMM·효과크기·CI 1차 + arm 분해 + forest plot + 선행연구 인용 비판 + 개선 가설).
4. 부트스트랩: `docs/plans/next_experiment_goal_v2_3.md` + 새 세션 [GOAL] + TickTick ai-continue 투두.
5. feature 브랜치 → 한글 PR → rebase 머지.

## 11. 리스크
| 리스크 | 완화 |
|---|---|
| 검정력 부족 → 유의성 미달 | 추정 중심 프레이밍, 효과크기·CI 1차, 검정력 사전 보고 |
| factorial 내 길이 교락 | 블록 토큰 직교화(T_block), placebo 2·T_block 매칭 |
| judge 동방향 편향·self-preference | blinding + 임계 sweep로 score 분포 노출 |
| RAG↔GitOps 중복 마스킹 | Jaccard 정량화, 임계 초과 시 런북 재작성 |
| 저품질 trial 신호 결손 | 플래그 + 포함/제외 sensitivity |
| placebo 우연 신호 | 무의미 보일러플레이트(실제 diff 금지) |
| seed best-effort 무효 | fingerprint 로깅 + 다수결 |
