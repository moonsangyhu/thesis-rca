# 실험 파이프라인 — 1가설 순차 실행

사용자가 "다음 실험 진행해", "실험 해줘" 등 실험 수행을 지시하면 **반드시 아래 단계를 순서대로** 실행한다. 클러스터가 1개이므로 **라운드당 1개 가설**만 실행한다. /deep-analysis에서 도출된 가설 중 사용자가 선택하거나 우선순위 1위를 실행한다.

## 파이프라인

```
Step 0.5: /deep-analysis  →  심층 분석 + 가설 후보 도출
         - 이전 실험 데이터 깊이 분석 (오답 패턴, 버전 간 추세, 컨텍스트 구조)
         - LLM/AIOps 기법 인터넷 서칭 참조
         - 개선 가설 후보 도출 + 데이터 근거 제시 + 우선순위 권장
         - 산출물: docs/surveys/deep_analysis_v{N}.md
         - commit-push
                                   ⬇
Step 1: @experiment-planner  →  선택된 가설의 상세 계획서 작성
         - /deep-analysis 결과를 기반으로 상세 실험 계획 수립
         - 산출물: docs/plans/experiment_plan_v{N}.md
         - commit-push
                                   ⬇
Step 2: @hypothesis-reviewer  →  가설 리뷰
         - 방법론 비평, 교란 변수, 대안 가설 → commit-push
         - 산출물: docs/plans/review_v{N}.md
                                   ⬇
Step 3: @code-reviewer  →  실험 코드 구현
         - experiments/v{N}/ 독립 모듈로 생성
         - --dry-run 검증 → /changelog → /commit-push
                                   ⬇
Step 4: @experiment  →  실험 실행
         - /lab-tunnel로 터널 연결 (오케스트레이터가 사전 수행)
         - nohup으로 실행, PID 확인 후 즉시 보고
         - /experiment-status로 모니터링
         - 완료 후 /lab-restore
                                   ⬇
Step 5: @results-critic  →  독립 비판 분석 (편향 차단)
         - **대화 맥락 없는 fresh sub-agent**(general-purpose)를 디스패치한다.
           오케스트레이터가 직접 쓰지 않는다 — "이번엔 성공했다"는 확증 편향 차단.
         - 입력: 결과 CSV·raw·로그, 해당 실험 plan/hypothesis, 그리고 선행연구
           (위키 ~/ms/wiki/wiki/ 탑다운 + repo docs/papers/·docs/surveys/).
         - 검증 게이트: superpowers:verification-before-completion — CSV 행 수·raw JSON
           개수·로그를 명령 실행 결과로 확인·인용. 가짜/추정 수치 금지.
         - 산출물: results/analysis_v{N}.md (아래 §Step5 필수 섹션)
         - commit-push
                                   ⬇
Step 6: 다음 실험 부트스트랩  →  실험 한 턴의 종결 게이트
         - Step 5 비판에서 도출된 **1순위 개선 가설**을 다음 실험 goal로 정리.
         - 산출물 ①: docs/plans/next_experiment_goal_v{N+1}.md
           (docs/templates/experiment_completion_goal.md 골 템플릿 기반, 치환 완료본)
         - 산출물 ②: 새 세션에서 바로 붙여넣을 [GOAL] 시작 프롬프트 (위 문서에 포함)
         - 산출물 ③: 그 프롬프트를 **TickTick `ai-continue` 리스트에 투두로 저장**
           (python3 ~/.claude/bin/tt_handoff.py < json — 토큰은 Keychain, 출력 금지)
         - 이 3개가 모두 생성돼야 "실험 한 턴 종료". commit-push → PR.
```

## Step 5 필수 섹션 (results/analysis_v{N}.md)

독립 분석 sub-agent는 아래 5개 섹션을 **반드시** 포함한다. ④·⑤가 이 단계의 핵심(비판·개선).

1. **데이터 검증** — CSV 행 수·raw JSON 개수·로그를 실제 명령 실행 결과로 확인·인용.
2. **통계 분석** — System A vs B McNemar χ²·p값, fault별/카테고리별 정확도, eval 점수 분포,
   이전 베이스라인 대비 추세. 미수집 fault 상태 명시.
3. **비판적 회고** — `rules/agents.md` §B의 plan critique 5축(구성·내적·외적·통계 타당성·대안 가설)을
   결과에 적용. **위키/repo 선행연구 대비** 우리 결과의 위치·부족점을 논문 정량 수치를 인용해 비판.
4. **개선 가설** — 비판에서 도출한 다음 실험 후보(우선순위·데이터 근거·논문 근거).
5. **결론·한계** — 이번 라운드 가설 성패 판정 + 일반화 한계.

## Step 6 TickTick 투두 형식

`@handoff` 스킬 메커니즘 재사용. `/tmp/tt-*.json`에 `{"title","content","tags"}` 작성 후
`python3 ~/.claude/bin/tt_handoff.py`로 생성. content 첫 줄 = 새 세션 재개 프롬프트 경로,
tags = `["claude-handoff", "thesis-rca"]`. 토큰 값 화면 출력 금지.

## 산출물 경로 (버전별)

| 산출물 | 경로 |
|-------|------|
| 실험 계획서 | `docs/plans/experiment_plan_v{N}.md` |
| 가설 리뷰 | `docs/plans/review_v{N}.md` |
| 실험 코드 | `experiments/v{N}/` |
| 실험 결과 | `results/experiment_results_v{N}.csv` |
| Raw 데이터 | `results/raw_v{N}/` |
| 분석 리포트(독립 비판) | `results/analysis_v{N}.md` |
| 다음 실험 goal | `docs/plans/next_experiment_goal_v{N+1}.md` |
| 다음 세션 재개 포인터 | TickTick `ai-continue` 투두 |
