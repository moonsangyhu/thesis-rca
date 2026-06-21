---
title: "다음 실험 V2.3 goal — RAG 검색 누출 통제 + 메커니즘 규명"
derived_from: "results/analysis_v2_2.md (V2.2 독립 비판 분석)"
created: 2026-06-22
prev_experiment: V2.2
next_slug: v2_3
---

# 다음 실험 V2.3 — goal 정리 + 새 세션 시작 프롬프트

> V2.2 종결 게이트(Step 6) 산출물. V2.2 독립 비판 분석(`results/analysis_v2_2.md`) §4의 1순위 개선 가설을 다음 실험 goal로 정리한다.

## 1. 왜 V2.3인가 (V2.2 비판 요약)

V2.2(5-arm 2×2 factorial+placebo, k=3 생성·m=3 blinded 채점, 임계 sweep, 60/60 수집)의 독립 비판 결론:

- **RAG 효과는 크고 임계 robust하나 메커니즘이 "정답 누출"**: C3_rag 65.0% vs C1 31.7%(+33.3%p, Cohen h=0.68, Newcombe CI[+20.7,+43.9]), 임계 0.5/0.6/0.7 모두 RAG 1위(V2.1 "0.5 인공물" 해소). **그러나 RAG 60건 중 45건(75%)이 주입 fault의 바로 그 런북**(파일명/제목=정답 라벨, 예 `rca-f11-networkdelay.md`)을 회수. 자기런북 회수 시 71% vs 미회수 47% → RAG 우위 대부분이 **검색 누출**(추론 아님).
- **GitOps = placebo (길이 효과)**: C2_gitops 36.7% = C5_placebo 36.7%, main effect 0. 단 GitOps 컨텍스트가 imperative 주입 하 fault 무관("Ready") + 복구버그 잔재(`Git repo not found`)로 **신호 자체가 손상** → "GitOps 무용"은 주입방식/신호결손의 산물일 수 있어 단정 보류.
- **interaction 음(−10%p)**: C4_both(60%) < C3_rag(65%). GitOps+RAG는 시너지가 아니라 간섭.
- **수집 교락**: F1–F8(1차) / F9–F12(2차, 클러스터 복구 후) 시점 분리 → arm 비교는 동일신호 공유로 내적 타당하나 카테고리 비교는 시점 교락.
- **측정 robustness는 대폭 개선**: judge m=3 만장일치 95.3%, blinding 코드 확인, gen_agreement 0.76, low_quality 0/300.

→ 결론: **RAG의 우위가 진짜 진단 추론인지 검색 누출인지 분리하기 전엔 논문 주장 불가.** V2.3은 P1(검색 누출 통제)을 최우선으로, GitOps 신호 정상화(P3)·수집 교락 제거(P5)를 함께 해결한다.

## 2. V2.3 목표 (독립변수·처치)

프레임워크 레벨만 (모델 `gpt-4o-mini` 고정). V2.2 5-arm·k=3·m=3·임계 sweep·추정 중심 프레이밍·길이 직교화는 **유지**.

### P1 (최우선) — RAG 검색 누출 제거 + retrieval ablation
- **blind retrieval**: 런북의 파일명·제목·진단명에서 fault 라벨 마스킹(예 `rca-f11-networkdelay.md`→중립 ID), 본문에서도 정답 라벨 토큰 제거.
- **누출 플래그 + stratified**: "주입 fault 자기런북 회수됨" 플래그 기록 → 회수/미회수 stratified 정확도 병기.
- **retrieval 내용 ablation arm**: ① full 런북, ② 절차(steps)만·진단명 제거(Flow-of-Action식 name/steps 분리), ③ 무관 런북(잘못된 fault) 주입. 통제 후에도 RAG 우위 잔존 시 진짜 추론 기여.

### P3 — GitOps 신호를 진단가능하게
- GitOps 컨텍스트를 fault와 연동(Git 매니페스트 경유 주입 또는 drift/sync 실패 반영)해 imperative 주입의 구조적 무신호를 제거. 복구버그(`/tmp/thesis-rca-work` 매니페스트 경로)도 영구 수정.

### P5 — 수집 교락 제거
- F1–F12를 **동일 캠페인·동일 복구이력**으로 일괄 재수집(시점 교락 제거). 사전 클러스터 복구 절차(recovery 매니페스트 경로 보장) 하네스화.

### (선택) P2/P4 — 후속 분리 가능
- P2 검정력: trial 5→15~20(C4vsC1 power 0.83@t10). 단 C4vsC5는 t20도 0.46 → 효과크기·CI 정밀화가 현실 목표.
- P4 interaction 음 원인: 컨텍스트 순서·위치 통제(Lost in the Middle), GitOps/RAG 분리 배치 arm.
> 범위가 크면 V2.3 = P1+P3+P5, P2/P4는 V2.4로. 새 세션 brainstorming에서 arm·trial·ablation 범위 확정.

## 3. 새 세션 시작 [GOAL] 프롬프트 (복사용)

```
[GOAL] K8s RCA 석사 실험 V2.3(RAG 검색 누출 통제 + 메커니즘 규명)을 설계·구현·실행·분석·부트스트랩까지 완전히 종료한다.

레포: /Users/yumunsang/thesis-rca (현재 main). 모든 작업은 PR-only 정책을 따른다.

■ 배경 (먼저 읽을 것)
- results/analysis_v2_2.md          ← V2.2 독립 비판 분석. 이 실험의 출발점(RAG=정답 누출).
- docs/plans/next_experiment_goal_v2_3.md ← 이 문서(V2.3 목표 P1/P3/P5 상세)
- docs/plans/experiment_plan_v2_2.md ← 직전 설계(5-arm·k3·m3·임계 sweep·추정 프레이밍)
- experiments/v2_2/                  ← 직전 하네스(여기서 V2.3 파생)
- rules/experiment-pipeline.md       ← 파이프라인(Step 0.5~6, 종결 게이트)
- rules/data-safety.md / docs/lab-environment.md ← 데이터 불변·모델 고정 / 랩 접속(터널·iface vmbr0)
- 메모리 recovery-manifest-path-bug ← 재실행 전 /tmp/thesis-rca-work/k8s 심볼릭 링크 필수(안 하면 trial 무더기 skip)

■ V2.3가 고치는 V2.2의 결함
- RAG 우위(65% vs 31.7%)의 75%가 자기런북(제목=정답) 회수=검색 누출. 추론 기여 미분리.
- GitOps 신호 손상(imperative 주입+복구버그)으로 main effect=0 단정 불가. 수집 2-campaign 시점 교락.

■ Definition of Done
1. (P1) blind retrieval(라벨 마스킹) + 누출 플래그·stratified + retrieval 내용 ablation arm 구현·--dry-run 검증.
2. (P3) GitOps 신호 fault 연동 + 복구 매니페스트 경로 영구 수정.
3. (P5) F1–F12 동일 캠페인·동일 복구이력 일괄 재수집(사전 복구 하네스화).
4. 독립 비판 분석가(fresh sub-agent)가 results/analysis_v2_3.md 작성(누출 통제 후 RAG 우위 잔존 여부·GLMM/CI·임계 sweep·선행연구 인용).
5. 다음 실험 부트스트랩: docs/plans/next_experiment_goal_v2_4.md + [GOAL] + TickTick ai-continue 투두.
6. feature 브랜치 → 한글 PR → rebase 머지.

■ 실행 절차 (rules/experiment-pipeline.md)
- Step 0.5 /deep-analysis (analysis_v2_2.md 기반 누출통제 기법 구체화)
- Step 1 @experiment-planner → docs/plans/experiment_plan_v2_3.md (HARD-GATE: 설계 승인 전 구현 금지)
- Step 2 plan critique 5축 → docs/plans/review_v2_3.md
- Step 3 코드 experiments/v2_3/ (blind retrieval·ablation arm·복구 하네스). --dry-run/--mock 검증.
- Step 4 /lab-tunnel → (재실행 전 심볼릭 링크) → nohup → /experiment-status(주기 보고) → /lab-restore
- Step 5 독립 비판 분석가 → results/analysis_v2_3.md
- Step 6 다음 실험 부트스트랩

■ 가드레일
- 모델 gpt-4o-mini 고정. 개선은 프레임워크(retrieval·ablation·신호) 레벨만.
- 기존 결과 CSV/raw/ground_truth 수정·삭제 금지. V2.3는 experiments/v2_3/·results/*_v2_3.*로 격리.
- main 직접 커밋·push·force·--no-verify·--admin 금지. feature → PR → rebase. 한국어.
- 긴 수집 캠페인 중 ~10분 간격 진행 보고. 라이브 fault 주입은 사용자 명시 승인 후.
- 재실행 전 클러스터 GREEN 확인 + recovery 매니페스트 경로(심볼릭 링크) 필수.

■ 종료(STOP) 조건
- (성공) DoD 1~6 충족 → 누출통제 후 RAG 우위·arm별 효과크기·CI·다음 goal 요약 보고 후 종료.
- (블록) 랩/키/환경 복구 불가 또는 같은 오류 3회 반복 → 현재 상태 보고 후 멈춤.
```

## 4. TickTick 등록 (Step 6)
위 [GOAL] 재개 포인터를 TickTick `ai-continue` 리스트에 투두로 저장(`python3 ~/.claude/bin/tt_handoff.py`). 본 문서 경로가 재개 포인터다.

## 5. 참고
- V2.2 분석: `results/analysis_v2_2.md`
- 골 템플릿: `docs/templates/experiment_completion_goal.md`
- 파이프라인: `rules/experiment-pipeline.md`
- recovery 버그 메모리: `recovery-manifest-path-bug`
