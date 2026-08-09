# Codex Operating Contract for `thesis-rca`

이 파일은 Claude Code 중심으로 운영되던 `thesis-rca`를 Codex에서도 같은 연구·실험 계약으로 수행하기 위한 repo-local 정본이다. Codex는 이 파일과 `CLAUDE.md`, 관련 `rules/*.md`, `.codex/config.toml`, `.codex/hooks.json`을 함께 따른다.

## Role Split

- **Codex is the orchestrator of record.** 완료 판단은 대화가 아니라 파일, git, 로그, 결과물 검증에 근거한다.
- **Claude Code is subordinate and optional.** 사용자가 Claude 병행을 요구하거나 독립 검토가 유용할 때만 bounded review/draft에 사용한다. Claude 출력만으로 완료를 주장하지 않는다.
- **Research-first advisor stance.** 연구질문, 단일 독립변수, baseline, evaluation, reproducibility, falsifiability를 우선하고 약한 주장과 미검증 결과를 명시한다.

## Startup Checklist

새 작업을 시작할 때 다음을 수행한다.

1. `git status --short --branch`로 branch와 dirty tree를 확인하고 사용자 변경을 보존한다.
2. `CLAUDE.md`, `docs/research-charter.md`, 작업과 관련된 `rules/*.md`를 읽어 현재 checkpoint를 확인한다.
3. `.codex/config.toml`과 `.codex/hooks.json`이 활성화됐는지 확인한다. Codex가 project hooks trust 검토를 요구하면 `/hooks`에서 정확한 정의를 검토·신뢰하기 전까지 쓰기/민감 명령을 멈춘다.
4. 기본 본류는 **Research Track**이다. 사용자가 명시적으로 실험 재개를 지시할 때만 Experiment Track에 진입한다.
5. 실험/분석 완료는 결과 파일, row count, raw count, 로그, 분석 산출물을 실제 명령으로 확인한 뒤에만 주장한다.

## Codex-native Surfaces

- 지속 규칙: `AGENTS.md` + `CLAUDE.md` + `rules/`
- repo skills: `.agents/skills/*/SKILL.md`; Claude slash command `/name`은 Codex `$name`과 대응한다.
- custom agents: `.codex/agents/*.toml`
  - `research_planner`, `experiment_planner`, `paper_writer`, `experiment`, `results_critic`
- lifecycle guard: `.codex/hooks.json` → `.codex/hooks/pretool_guard.py`
- superpowers: 공식 Codex `superpowers@openai-curated` plugin의 skills를 사용한다.

Claude 원본 skill과 agent 파일은 domain workflow의 단일 정본으로 유지한다. Codex wrapper/custom agent는 원본 파일을 끝까지 읽고 도구명만 현재 Codex 표면으로 번역한다. 사용자 지시, 이 파일, Codex 안전 정책이 충돌 시 우선한다.

## Hook Enforcement

Codex `PreToolUse` adapter는 Claude guard와 동일한 정책을 실제 집행한다.

- Bash: `pr-only-guard.sh` → `experiment-guard.sh` → `bash-guard.sh`
- apply_patch/Edit/Write: patch target과 추가 내용을 추출해 `claude-config-guard.sh` → `data-guard.sh` → `secret-scanner.sh`
- Agent: `agent-model-guard.sh` 호환 경고

훅을 우회하는 option을 사용하지 않는다. specialized/hosted tool처럼 hook coverage 밖인 쓰기 작업도 같은 정책을 수동 적용한다.

## Git Workflow

- main 직접 commit·merge·push 금지. 모든 변경은 feature branch와 PR을 거친다.
- 정규 마무리: feature branch → push → 한국어 PR → 사용자 승인 → `gh pr merge --rebase --delete-branch`.
- `--force`, `--force-with-lease`, `--no-verify`, `--no-gpg-sign`, `--admin` 금지.
- commit/PR 제목과 본문은 한국어로 작성한다. AI attribution은 사용자가 요구하지 않는 한 추가하지 않는다.
- 파일별로 명시해 stage하며 `.DS_Store`, credentials, secret, 불필요한 binary를 추적하지 않는다.

## Research Track — Default

Trigger: 논문 조사, 선행연구, 자료조사, 포지셔닝, 관련연구.

1. `rules/research-pipeline.md` R-1에 따라 scope를 정하고 사용자 승인 전 검색하지 않는다.
2. 논문 전문을 `$paper-reader`로 읽어 `docs/papers/{slug}.md`에 한 편씩 기록한다.
3. `$paper-survey`로 `docs/surveys/paper_survey_v{N}.md`를 작성한다.
4. 5편 이상, 각 논문의 1차 출처, 정량 수치, 본 논문 적용 가능성을 검증한다.
5. 검색이 필요한 문헌·최신 사실은 web으로 확인하며 기억으로 출처나 수치를 만들어내지 않는다.

## Experiment Track — Explicit Instruction Only

Trigger: 실험 진행/재개, V9 실행, fault injection 실행 등 사용자의 명시적 지시.

1. `rules/experiment-pipeline.md`, `rules/data-safety.md`, `docs/lab-environment.md`, 승인된 plan을 확인한다.
2. LLM model은 `gpt-4o-mini`로 고정하고 framework/context/RAG/harness만 개선한다.
3. `$lab-tunnel`은 기존 tunnel health를 먼저 확인해 정상이면 재사용한다. K8s API, Prometheus, Loki, cluster state, output path를 preflight한다.
4. 장시간 실험은 background process로 시작하고 PID/log/result path를 즉시 보고한다.
5. 실험 중 git 상태 변경 금지. 완료 후 `$lab-restore`와 row/raw/log/analysis 검증을 수행한다.
6. `results/*.csv`, `results/raw_v*/*.json`, `results/ground_truth.csv`는 수정·삭제하지 않는다.
7. Step 5 분석은 fresh `results_critic` agent에 맡겨 confirmation bias를 줄이고, Step 6의 next goal·새 session prompt·TickTick handoff가 모두 있어야 한 round가 끝난다.

## Superpowers Mapping

- session/task entry: `using-superpowers`
- research/experiment design: `brainstorming`; scope/design 승인 전 검색·구현 금지
- multi-step implementation: `writing-plans`
- execution: `executing-plans` 또는 `subagent-driven-development`
- debugging: `systematic-debugging`
- completion claim: `verification-before-completion`
- branch finish: `finishing-a-development-branch` option 2 → `$pr-merge`

산출물 경로는 `CLAUDE.md`의 **Output Path Mapping**을 따르고 `docs/superpowers/` 기본 경로를 사용하지 않는다.

## Reporting Standard

한국어로 짧은 결론부터 말하고 다음을 구분한다.

- **판단/관찰한 사실**: git 상태, 파일, 로그, row count 등 확인된 내용
- **근거/정책**: `CLAUDE.md`, `rules/`, hooks, 논문/결과 출처
- **리스크/가정**: 아직 검증되지 않은 추론과 한계
- **다음 액션**: 바로 실행 가능한 checkpoint 한 단계

코드·문서·설정을 수정했으면 `$changelog`를 수행하고, 완료 직전 실제 검증 명령 결과를 확인한다.
