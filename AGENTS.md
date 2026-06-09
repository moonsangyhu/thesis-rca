# Hermes Operating Contract for `thesis-rca`

이 파일은 Claude Code 중심으로 운영되던 `thesis-rca`를 Hermes/Slack에서 이어서 수행하기 위한 repo-local 운영 계약이다. Hermes는 이 파일과 `CLAUDE.md`, `rules/`, `.claude/settings.json`을 함께 읽고, Claude Code 훅이 자동 실행되지 않는 점을 수동으로 보완한다.

## Role Split

- **Hermes is the orchestrator of record.** 실험·문헌조사·분석의 상태 판단은 파일, git, 로그, 결과물 검증에 근거한다.
- **Claude Code is subordinate.** Claude는 bounded task에만 사용한다: 코드 리뷰, 국소 구현 제안, 로그/결과 해석 초안, 문서 초안. Claude TUI 대화 내용만으로 완료를 주장하지 않는다.
- **Research-first advisor stance.** 연구질문, 독립변수, baseline, evaluation, reproducibility, falsifiability를 우선한다. 약한 주장이나 미검증 결과는 명확히 표시한다.

## Startup Checklist

새 작업을 시작하면 먼저 다음을 확인한다.

1. `git status --short --branch`로 현재 브랜치와 dirty tree 확인.
2. `CLAUDE.md`와 관련 `rules/*.md`를 읽어 현재 트랙 확인.
3. `.claude/settings.json`의 hook 목록을 확인하고, Hermes 도구 사용 전 아래 hook-equivalent guard를 수동 적용.
4. 현재 본류는 기본적으로 **Research Track**이다. 사용자가 명시적으로 실험 재개를 지시할 때만 Experiment Track으로 진입한다.
5. 실험/분석 완료 주장은 결과 파일, row count, 로그, 분석 산출물 검증 후에만 한다.

## Claude Harness Equivalence

Hermes의 `terminal`, `write_file`, `patch`는 Claude Code `PreToolUse` hook을 자동 실행하지 않는다. 따라서 다음 정책을 수동으로 지킨다.

### Write/Edit/Patch guard

파일 수정 전 다음 정책을 적용한다.

- `hooks/claude-config-guard.sh`: `claude-config` 브랜치에서 Claude 설정 외 파일 수정 금지.
- `hooks/data-guard.sh`: 원본 실험 데이터 수정 금지.
  - `results/*.csv`
  - `results/raw_v*/*.json`
  - `results/ground_truth.csv`
- `hooks/secret-scanner.sh`: 비밀값 유입 방지.

수정하려는 경로가 애매하면 아래 형식으로 hook을 smoke-test한다.

```bash
printf '%s' '{"tool_input":{"file_path":"/absolute/path/to/file"}}' | ./hooks/data-guard.sh
```

### Bash guard

shell 명령 실행 전 다음 정책을 적용한다.

- `hooks/pr-only-guard.sh`: main 직접 commit/merge/rebase/push, force push, `--no-verify`, `--admin` merge 금지.
- `hooks/experiment-guard.sh`: 실험 실행 중 branch 변경, commit, push 등 실험 교란 행위 금지.
- `hooks/bash-guard.sh`: 파괴적 파일/DB 명령 금지.

민감한 명령은 아래 형식으로 hook을 먼저 통과시킨다.

```bash
printf '%s' '{"tool_input":{"command":"git status --short"}}' | ./hooks/pr-only-guard.sh
```

## Git Workflow

- main 브랜치 직접 커밋·머지·푸시 금지.
- 모든 변경은 feature branch에서 수행하고 PR로 반영한다.
- 정규 마무리: feature branch → push → 한국어 PR → 사용자 승인 → `gh pr merge --rebase --delete-branch`.
- `--force`, `--no-verify`, `--admin` 금지.
- 커밋 메시지와 PR 제목/본문은 한국어로 작성한다.
- 불필요한 macOS `.DS_Store`는 추적하지 않는다.

## Track Rules

### Research Track — current default

Trigger: 논문 조사, 선행연구, 자료조사, 포지셔닝, 관련연구.

1. 범위 확정: `rules/research-pipeline.md`의 R-1을 따른다. 검색 전 scope 승인 gate를 둔다.
2. 논문별 읽기: `docs/papers/{slug}.md`에 정리한다.
3. 종합 서베이: `docs/surveys/paper_survey_v{N}.md`에 정리한다.
4. 완료 검증: 5개 이상 논문, URL/DOI/arXiv 등 출처, 정량 수치, 본 논문 적용 가능성을 확인한다.

### Experiment Track — only on explicit instruction

Trigger: 실험 진행, 실험 재개, V9 실행, fault injection 실행.

1. 실험 전 `rules/experiment-pipeline.md`, `rules/data-safety.md`, `docs/lab-environment.md`를 확인한다.
2. 모델은 `gpt-4o-mini`로 고정한다. 개선은 프레임워크/컨텍스트/RAG/하네스 수준에서만 한다.
3. 실험 전 preflight: 터널, Kubernetes API, Prometheus, Loki, cluster state, result output path 확인.
4. 장시간 실행은 background process로 시작하고 PID/log/result path를 즉시 보고한다.
5. 완료 후 row count, raw JSON 개수, 로그 에러, 분석 스크립트 결과를 검증한다.
6. 원본 결과 CSV/raw JSON/ground truth는 직접 수정하지 않는다.

## Reporting Standard

사용자에게 보고할 때는 다음을 구분한다.

- **관찰한 사실**: git 상태, 파일 존재, 로그, 결과 row count 등.
- **정책/제약**: CLAUDE.md, rules, hooks에서 온 규칙.
- **가정**: 아직 검증되지 않은 추론.
- **다음 실행 체크포인트**: 바로 실행 가능한 한 단계.

논문 연구 답변은 한국어로 짧은 결론부터 말하고, 가능하면 `판단 / 근거 / 리스크 / 다음 액션` 구조를 사용한다.

## Claude Code Usage from Hermes

Claude를 호출할 때는 기본적으로 print mode를 사용한다.

```bash
claude -p 'Review the current diff for policy violations and missing verification.' \
  --allowedTools 'Read,Bash' \
  --max-turns 5
```

Interactive Claude TUI는 장시간 탐색이 필요할 때만 tmux로 띄운다. 종료 후 반드시 파일 diff와 검증 명령으로 결과를 확인한다.
