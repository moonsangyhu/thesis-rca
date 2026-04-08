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
Step 5: @results-writer  →  결과 분석
         - 이전 베이스라인 대비 성능 비교
         - 산출물: results/analysis_v{N}.md
         - commit-push
```

## 산출물 경로 (버전별)

| 산출물 | 경로 |
|-------|------|
| 실험 계획서 | `docs/plans/experiment_plan_v{N}.md` |
| 가설 리뷰 | `docs/plans/review_v{N}.md` |
| 실험 코드 | `experiments/v{N}/` |
| 실험 결과 | `results/experiment_results_v{N}.csv` |
| Raw 데이터 | `results/raw_v{N}/` |
| 분석 리포트 | `results/analysis_v{N}.md` |
