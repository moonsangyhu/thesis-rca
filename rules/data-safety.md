# 데이터 안전 & 실험 격리 규칙

## 모델 고정

실험 간 LLM 모델(`gpt-4o-mini`)은 **반드시 고정**. 개선은 프레임워크(프롬프트, 컨텍스트, 하네스, RAG) 레벨에서만 시도한다.

## 데이터 불변 (hooks/data-guard.sh로 강제)

- `results/*.csv` — 원본 실험 결과 데이터. **수정·삭제 절대 금지**
- `results/raw_v*/*.json` — Raw 실험 데이터. **수정·삭제 절대 금지**
- `results/ground_truth.csv` — Ground truth. **수정·삭제 절대 금지**

분석 리포트(`results/analysis_v*.md`)와 변경 기록(`results/experiment_changes_v*.md`)은 쓰기 허용.

## 실험 격리 (hooks/experiment-guard.sh로 강제)

실험 실행 중에는 다음 행위 **절대 금지**:
- `git commit`, `git push`, `git checkout`, `git switch`, `git merge`, `git rebase`
- 브랜치 변경 등 실험을 중단시킬 수 있는 모든 행위

## 실험 중 코드 수정 절차

실험 중 코드 수정이 필요하면 반드시 아래 순서를 따른다:

1. 실험 중단
2. 코드 수정
3. `/changelog` — 변경 이력 기록
4. `/commit-push` — 커밋·푸시
5. 실험 재개
