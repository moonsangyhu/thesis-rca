# 실험 계획서 V2.2 — 측정 신뢰성 + 처치 분해

> 작성: 2026-06-20 (Step 1 brainstorming 산출물, 기본 경로 override)
> 입력: results/analysis_v2_1.md(V2.1 독립 비판), docs/surveys/deep_analysis_v2_2.md(Step 0.5)
> 설계 확정(사용자 승인): **5-arm · 생성 k=5 · 동일 gpt-4o-mini judge(m=3) · F1–F12 전체**
> 모델 `gpt-4o-mini` 고정. 개선은 프레임워크 레벨에서만.

## 1. 가설

> **H:** GitOps 컨텍스트와 RAG 런북은 각각, 그리고 컨텍스트 길이 효과와 분리해 측정했을 때 LLM RCA 정확도를 높이며, 그 결론은 채점 임계값·샘플링 노이즈에 robust하다.

V2.1은 "B(GitOps∪RAG) > A"를 방향만 지지(McNemar p=0.267)하고 ① 채점 임계 0.5 인공물(0.6에서 역전), ② 묶음 처치+토큰 +38% 길이 교락, ③ 채점 비결정성, ④ 단일 측정으로 미입증. V2.2는 가설 재검증 전에 **측정·설계 자체**를 고친다.

## 2. 독립변수 — 5-arm 처치 구조 (P2)

(fault,trial)당 **fault injection·신호 수집은 1회**. 5개 arm이 그 **동일 신호**를 받아 컨텍스트만 다르게 구성한다(arm은 cluster cooldown을 늘리지 않고 LLM 호출만 늘림).

| arm 코드 | 컨텍스트 구성 | 역할 |
|---|---|---|
| `C1_A` | observability only (kubectl + Prometheus + Loki) | baseline |
| `C2_gitops` | A + GitOps(FluxCD status + git diff) | GitOps main effect |
| `C3_rag` | A + RAG 런북 retrieval | RAG main effect |
| `C4_both` | A + GitOps + RAG (= 기존 System B) | full / interaction |
| `C5_placebo` | A + **C4와 토큰 수 matched된 무관 filler 텍스트** | 길이 교락 통제 |

**2×2 factorial 분해 (GitOps × RAG):**
- GitOps main = (C2+C4) − (C1+C3)
- RAG main = (C3+C4) − (C1+C2)
- interaction = (C4−C2) − (C3−C1)

**판정 게이트(핵심):** `C4 > C5 > C1`이 통계적으로 유의해야 "GitOps+RAG **내용**의 순기여"를 주장한다. C5(placebo)도 C1보다 오르면 개선의 일부/전부는 **토큰 증가 효과**(Power of Noise, arXiv:2401.14887).

**Confound 통제:**
- RAG 런북이 GitOps 정보를 중복 회수하지 않게 두 소스 분리(main effect 상호 마스킹 방지).
- placebo filler = 다른 fault의 GitOps diff/셔플 로그 등 **주제 인접하나 해당 장애와 무관**한 텍스트, C4와 토큰 수 ±5% 매칭.
- 컨텍스트 삽입 위치 통제(Lost in the Middle, arXiv:2307.03172) — 모든 arm 동일 위치/순서.

## 3. 측정 robustness (P1)

### 3-1. 생성 — self-consistency k=5
- 각 arm을 `temperature=0.7`로 **k=5회 샘플**.
- 다수결 단위 = `identified_fault_type`(이산 라벨) 최빈값. 동률 시 첫 샘플 우선(결정적 tie-break).
- 5샘플 각각의 `identified_fault_type`·`correctness_score`·`confidence`를 raw JSON에 보존(분포 분석용).
- 근거: Self-Consistency(arXiv:2203.11171, T=0.7), RCAgent(arXiv:2310.16340, RCA 도메인 k≈20 saturation이나 k=5에서 대부분 이득).

### 3-2. 채점 — judge 다수결 m=3
- 동일 `gpt-4o-mini` judge, `temperature≈0 + seed 고정 + reference rubric(ground_truth 제공)`.
- **m=3회 호출 다수결**로 채점 비결정성(V2.1 결함 #3: 동일 답 0.1/0.5 갈림) 완화.
- 근거: temp=0도 비결정 잔존(arXiv:2503.09347) → 다수결 필수. reference-guided(arXiv:2306.05685, 실패율 70→15%).

### 3-3. 점수 보존 + 임계 sweep
- `correctness_score`를 **이진화하지 않고 원점수 보존**(arm×k 분포 전부 CSV/raw 기록).
- correct/incorrect 이진화는 **사후**에 **임계 0.5/0.6/0.7 sweep**으로 산출, 분석에 3개 전부 병기.
- 근거: V2.1 결함 #2 — 결론이 0.5 임계에 의존, 0.6에서 역전.

## 4. 통계 분석 (Step 5에서 독립 분석가가 수행)

반복측정(5 trials/fault)을 60 독립건으로 McNemar에 넣으면 거짓 정밀도 → 올바른 절차:
1. **1차:** fault당 정확률 집계(12 item) 후 arm 쌍 비교 — **exact binomial McNemar**(discordant b+c 작음) + **Cohen's h** 효과크기 + **Newcombe hybrid score CI**.
2. **다중 arm:** **Cochran's Q** omnibus → 유의 시 **post-hoc McNemar + Bonferroni 보정**.
3. **임계 sweep(0.5/0.6/0.7)** 결과를 모든 비교에 병기.
4. **보조:** GLMM(fault random effect)로 반복측정 정석 확인.
5. 검정력 부족 시 "비유의 ≠ 효과 없음" 명시. 경계값(b+c<25, Cohen band)은 휴리스틱임을 주석.

## 5. 구현 설계 (experiments/v2_2/, v2_1 파생)

| 파일 | 변경 |
|---|---|
| `experiments/shared/llm_client.py` | `call_llm()`에 `temperature`·`seed` 인자 추가; `judge_correctness()` → `judge_correctness_voted(m=3)` 다수결, 원점수 리스트 반환 |
| `experiments/shared/runner.py` | trial 내부: 신호수집 1회 → **5-arm 루프** × **생성 k=5 루프**; arm별 컨텍스트 빌드·집계 |
| `src/processor/context_builder.py` | arm 토글(`C1_A`/`C2_gitops`/`C3_rag`/`C4_both`/`C5_placebo`); **placebo filler 생성기**(토큰 매칭) |
| `experiments/v2_2/config.py` | CSV에 `arm`, `gen_samples_json`(k=5 분포), `correctness_scores_json`(m=3), `correct@0.5/0.6/0.7` 컬럼 |
| `experiments/v2_2/run.py` | v2_1 파생, version=v2_2, arm/k/m CLI 인자 |
| `experiments/v2_2/analyze_v2_2.py` (신규) | §4 통계(McNemar·Cohen's h·Newcombe CI·Cochran Q·임계 sweep·factorial 분해) |

**검증:** `--dry-run`(실 클러스터 미접속, mock 신호)으로 5-arm × k=5 × m=3 루프·CSV 스키마·집계 로직 end-to-end 확인 후에만 실 수집.

## 6. 종속변수·기록

- **주 종속변수:** arm별 정확도(임계 0.5/0.6/0.7 각각), fault별/카테고리별.
- **부 종속변수:** 생성 다수결 일치율(k=5 내 합의도), judge 다수결 일치율(m=3), confidence 보정, latency·토큰.
- CSV: `results/experiment_results_v2_2.csv`, raw: `results/raw_v2_2/`(arm별 5샘플+3채점 분포 보존).

## 7. 규모·실행 절차

- 규모: 12 fault × 5 trial × 5 arm × (k=5 생성 + m=3 채점) ≈ **2,850 LLM 호출**. 직렬 ~14h(cooldown ~6h 포함). arm/샘플 독립 → LLM 호출 병렬화로 단축.
- Step 4: `/lab-tunnel` → `nohup` 실행 → `/experiment-status` 모니터(~10분 간격 보고) → `/lab-restore`.
- ⚠️ **전제조건:** `OPENAI_API_KEY` 설정(현재 미설정), 랩 터널 GREEN(Preflight는 2026-06-19 달성).

## 8. 가드레일·격리

- 모델 `gpt-4o-mini` 고정. 개선은 프레임워크(반복·ablation·채점) 레벨에서만.
- 기존 결과 CSV/raw/ground_truth 수정·삭제 금지. `experiments/v2_2/`·`results/*_v2_2.*`로 격리.
- main 직접 커밋·push·force·--no-verify·--admin 금지. feature 브랜치 `exp/v2_2-measurement-ablation` → 한글 PR → rebase 머지.

## 9. Definition of Done

1. P1 하네스(k=5 생성 + m=3 채점 다수결 + seed 고정 + 임계 sweep) 구현·--dry-run 검증.
2. P2 5-arm(C1~C5) 구현·수집.
3. 독립 비판 분석가(fresh sub-agent)가 `results/analysis_v2_2.md` 작성(§4 통계 + arm 분해 + 선행연구 인용 비판 + 개선 가설).
4. 부트스트랩: `docs/plans/next_experiment_goal_v2_3.md` + 새 세션 [GOAL] + TickTick ai-continue 투두.
5. feature 브랜치 → 한글 PR → rebase 머지.

## 10. 리스크

| 리스크 | 완화 |
|---|---|
| LLM 호출 4~7배 → 비용·시간 | arm/샘플 독립 병렬화; k=3 fallback |
| arm당 trial=5 → interaction 검정력 약함 | 결과에 검정력 명시, Cohen's h 병기 |
| RAG↔GitOps 정보 중복 → main effect 마스킹 | 소스 분리, 중복 점검 |
| placebo filler가 우연히 유의미 신호 포함 | 무관성 수동 검수, 토큰만 매칭 |
| judge 다수결도 인플레이션 잔존 | 임계 sweep로 score 분포 노출, eval 점수는 품질근거로 미사용 |
