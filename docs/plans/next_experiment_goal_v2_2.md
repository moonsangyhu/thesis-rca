---
title: "다음 실험 V2.2 goal — 측정 신뢰성 + 처치 분해"
derived_from: "results/analysis_v2_1.md (V2.1 독립 비판 분석)"
created: 2026-06-20
prev_experiment: V2.1
next_slug: v2_2
---

# 다음 실험 V2.2 — goal 정리 + 새 세션 시작 프롬프트

> 이 문서는 V2.1 종결 게이트(Step 6)의 산출물이다. V2.1 독립 비판 분석(`results/analysis_v2_1.md`)에서
> 도출된 1·2순위 개선 가설을 다음 실험 goal로 정리하고, 새 세션에서 그대로 붙여넣을 [GOAL] 프롬프트를 담는다.

## 1. 왜 V2.2인가 (V2.1 비판 요약)

V2.1(re-baseline, F1–F12 전체 수집)의 독립 비판 분석 결론:

- **B>A는 통계적으로 미입증**: McNemar χ²(cc)=1.23, exact p=0.267 (n=13 불일치 쌍). 방향만 B 우위.
- **결정적 결함 — 채점 임계값 인공물**: correctness_score 0.5 임계에선 B 43.1% vs A 34.5%(+8.6%p)지만,
  **0.6 임계에선 역전**(A 25.9% vs B 22.4%). B 정답 25개 중 12개(48%)가 정확히 경계값 0.5.
- **B 우위의 출처 편중**: 거의 전적으로 node-level 단일 fault F4(NodeNotReady, B 4/5 vs A 1/5). service-level은 +2.3%p로 미미.
- **묶음 처치 + 길이 교락**: 독립변수가 "GitOps 컨텍스트 ∪ RAG 런북" 묶음 + prompt 토큰 +38%. 어느 컴포넌트/길이가 효과인지 분리 불가.
- **LLM-judge 점수 무효**: eval grounding 8.8~9.1/10인데 실제 정확도 34~43% (무상관, 인플레이션).
- **채점 비결정성**: 동일 답(F12 t2)이 A=0.1/B=0.5로 갈려 채점.

→ 결론: **결과를 신뢰하려면 가설 재검증보다 "측정 자체"를 먼저 고쳐야 한다.** V2.2는 P1(채점 robustness)·P2(처치 분해)를 해결한다.

## 2. V2.2 목표 (독립변수·처치)

프레임워크 레벨 개선만 (모델 `gpt-4o-mini` 고정 유지). 두 축:

### P1 — 측정 robustness (최우선)
- 각 (fault,trial)을 **k=3~5회 반복 샘플**해 정확도를 비율로 측정(단일 측정 → 분포).
- **채점기 다중 호출 다수결** + seed/temperature 고정으로 채점 비결정성 제거.
- **임계값 sweep(0.5/0.6/0.7)** 결과를 항상 병기 + 신뢰구간·효과크기 보고.

### P2 — 처치 분해 (3-arm+ ablation)
- arm 분해: **A(baseline) / B-GitOps-only / B-RAG-only / B-both**.
- **길이 통제 placebo arm**(무관 텍스트로 토큰만 B-both에 맞춤) 추가 → "내용 효과 vs 컨텍스트 길이 효과" 분리.
- Flow-of-Action ablation(−38.67pp 분리 측정) 방식 차용.

### (선택) P3/P4 — 후속 라운드로 분리 가능
- P3: 네트워크 fault(F11/F12) 전용 신호(node_network_*, TCP retransmit, Cilium drop) 보강 + Loki timeout 대비.
- P4: validator on/off 순효과 분리.
> 범위가 크면 V2.2 = P1+P2만, P3/P4는 V2.3로. 새 세션 brainstorming에서 arm 수·k·fault 범위를 확정한다.

## 3. 새 세션 시작 [GOAL] 프롬프트 (복사용)

아래 블록을 새 Claude Code 세션의 `/goal`에 그대로 붙여넣으면 V2.2가 시작된다. 이 실험은 새 코드(반복 샘플·ablation arm·임계 sweep)가 필요하므로, 수집·분석만 하던 V2.1과 달리 **실험 파이프라인 전체(brainstorming→plan→code→run→독립 분석→부트스트랩)**를 탄다.

```
[GOAL] K8s RCA 석사 실험 V2.2(측정 신뢰성 + 처치 분해)를 설계·구현·실행·분석·부트스트랩까지 완전히 종료한다.

레포: /Users/yumunsang/thesis-rca (현재 main). 모든 작업은 PR-only 정책을 따른다.

■ 배경 (먼저 읽을 것)
- results/analysis_v2_1.md          ← V2.1 독립 비판 분석. 이 실험의 출발점.
- docs/plans/next_experiment_goal_v2_2.md ← 이 문서(V2.2 목표 P1/P2 상세)
- rules/experiment-pipeline.md      ← 실험 파이프라인(Step 0.5~6, 종결 게이트 포함)
- rules/data-safety.md              ← 데이터 불변·모델 고정·실험 격리
- docs/lab-environment.md           ← 재구축 K8s 랩 접속(터널/노드/iface=vmbr0)
- experiments/v2_1/                  ← 직전 하네스(여기서 V2.2 모듈 파생)

■ V2.2가 고치는 V2.1의 결함
- B>A 미입증(McNemar p=0.267)이고 채점 임계 0.5의 인공물(0.6에서 역전).
- 독립변수가 "GitOps∪RAG" 묶음 + 토큰 +38% 길이 교락. 단일 측정·채점 비결정성.

■ Definition of Done
1. (P1 측정 robustness) 각 케이스 k회 반복 샘플 + 채점 다수결 + seed 고정 + 임계 sweep(0.5/0.6/0.7) 하네스 구현.
2. (P2 처치 분해) A / B-GitOps-only / B-RAG-only / B-both (+길이 통제 placebo) arm 구현·수집.
3. 데이터 수집 후 독립 비판 분석가(fresh sub-agent)가 results/analysis_v2_2.md 작성
   (McNemar + 임계 sweep + arm별 분해 + 위키/repo 선행연구 인용 비판 + 개선 가설).
4. 다음 실험 부트스트랩: docs/plans/next_experiment_goal_v2_3.md + 새 세션 [GOAL] 프롬프트 + TickTick ai-continue 투두.
5. feature 브랜치 → 한글 PR → rebase 머지까지 완료.

■ 실행 절차 (rules/experiment-pipeline.md)
- Step 0.5 /deep-analysis (analysis_v2_1.md 기반 P1/P2 구체화)
- Step 1 @experiment-planner → docs/plans/experiment_plan_v2_2.md (HARD-GATE: 설계 승인 전 구현 금지)
- Step 2 plan critique 5축 리뷰 → docs/plans/review_v2_2.md
- Step 3 코드 구현 experiments/v2_2/ (반복 샘플·arm·임계 sweep). --dry-run 검증.
- Step 4 /lab-tunnel → nohup 실행 → /experiment-status 모니터(주기 보고) → /lab-restore
- Step 5 독립 비판 분석가 디스패치 → results/analysis_v2_2.md
- Step 6 다음 실험 부트스트랩(goal 문서 + TickTick 투두)

■ 가드레일
- 모델 gpt-4o-mini 고정. 개선은 프레임워크(반복·ablation·채점) 레벨에서만.
- 기존 결과 CSV/raw/ground_truth 수정·삭제 금지. V2.2는 별도 experiments/v2_2/·results/*_v2_2.* 로 격리.
- main 직접 커밋·push·force·--no-verify·--admin 금지. feature 브랜치 → PR → rebase 머지. 한국어.
- 긴 대기(수집 캠페인) 중에는 침묵 말고 ~10분 간격 진행 보고.

■ 종료(STOP) 조건
- (성공) DoD 1~5 충족 → arm별 정확도·McNemar p·임계 sweep 결과·다음 goal 한 줄 요약 보고 후 종료.
- (블록) 랩/키/환경 복구 불가 또는 같은 오류 3회 반복 → 현재 상태 보고 후 멈춤.
```

## 4. TickTick 등록 (Step 6)

위 [GOAL] 프롬프트의 재개 포인터를 TickTick `ai-continue` 리스트에 투두로 저장한다
(`python3 ~/.claude/bin/tt_handoff.py`). 본 문서 경로가 곧 재개 포인터다.

## 5. 참고
- V2.1 분석: `results/analysis_v2_1.md`
- 골 템플릿: `docs/templates/experiment_completion_goal.md`
- 파이프라인: `rules/experiment-pipeline.md` (Step 5 독립 비판 분석 + Step 6 부트스트랩)
