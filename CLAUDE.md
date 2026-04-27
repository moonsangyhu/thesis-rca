# K8s RCA 석사 논문 실험 플랫폼

> 🛡️ 이 워크트리는 **Claude 설정 전용**(`claude-config` 브랜치)입니다. `hooks/claude-config-guard.sh`가 Claude 관련 경로(`.claude/**`, `CLAUDE.md`, `rules/agents.md`, `hooks/{claude-config-guard,pr-only-guard,agent-model-guard}.sh`, `.gitignore`) 외의 Write/Edit/MultiEdit를 차단합니다. 도메인 파일 수정은 메인 워크트리(`/Users/yumunsang/Documents/thesis-rca`, `main` 브랜치)에서 수행하세요.

GitOps 컨텍스트(FluxCD/ArgoCD) 추가 시 LLM 기반 장애 원인 분석 정확도 향상을 검증한다.

- **System A**: Prometheus + Loki + kubectl → LLM
- **System B**: System A + GitOps + RAG → LLM
- 10 fault types (F1–F10) × 5 trials = 50 cases
- **모델 고정**: gpt-4o-mini 고정. 개선은 프레임워크 레벨에서만

문서·프롬프트는 한국어, 코드·변수명은 영어.

## Superpowers First

이 레포의 모든 작업(실험·자료조사·문서·코드)은 **superpowers 플러그인을 진입점으로** 시작한다.

- **세션 시작**: `superpowers:using-superpowers`(자동) — 어떤 스킬이 있는지 인지하고, 1%라도 적용 가능하면 호출.
- **창의·설계 작업 직전**: `superpowers:brainstorming` — 가설 수립, 자료조사 범위 결정, 코드 변경 설계는 모두 brainstorming부터. **HARD-GATE**: 사용자가 design을 승인하기 전에는 구현·검색·코드 작성 금지.
- **다단계 구현 직전**: `superpowers:writing-plans` — bite-size task로 분해된 plan 문서 작성.
- **Plan 실행**: `superpowers:executing-plans` 또는 `superpowers:subagent-driven-development` — review checkpoint마다 사용자 보고.
- **완료 직전**: `superpowers:verification-before-completion` — "검증 명령어를 실행한 결과"를 첨부하기 전엔 완료 주장 금지.
- **브랜치 마무리**: `superpowers:finishing-a-development-branch` → 옵션 2(Push and create a PR) → 본 레포 도메인 스킬 `/pr-merge`로 이행.

도메인 스킬·에이전트(아래 Tracks 참조)는 superpowers 흐름의 **task 단위**로 호출된다. 단독 호출도 가능하지만, 새로 시작하는 작업은 brainstorming부터 진입한다.

## Tracks

이 레포는 두 개의 1급 워크플로우(트랙)를 운영한다.

### Experiment Track — K8s RCA 실험 사이클

```
Step 0   superpowers:using-superpowers          (세션 진입)
Step 0.5 /deep-analysis                         → docs/surveys/deep_analysis_v{N}.md
Step 1   superpowers:brainstorming              ← @experiment-planner wrapper가 호출
                                                → docs/plans/experiment_plan_v{N}.md
Step 2   superpowers:writing-plans              (방법론 비평 = plan critique 5축)
                                                → docs/plans/review_v{N}.md
Step 3   superpowers:code-reviewer agent        ← experiments/v{N}/ 코드 + results/experiment_changes_v{N}.md
Step 4   superpowers:executing-plans            ← @experiment (lab-tunnel → nohup → status → lab-restore)
                                                → results/experiment_results_v{N}.csv, raw_v{N}/
Step 5   superpowers:verification-before-completion + 도메인 분석
                                                → results/analysis_v{N}.md
Step 6   superpowers:finishing-a-development-branch → /pr-merge
```

### Research Track — 선행 연구 자료조사 사이클

```
"논문 조사" 트리거
  ↓
R-1   superpowers:brainstorming                 (검색 키워드·기간·범위 5–8문항)
  ↓                                              HARD-GATE: plan 승인 전 검색 금지
R-2   superpowers:dispatching-parallel-agents   (키워드 N개 → N개 sub-agent)
                                                → 각 sub-agent: WebSearch + /paper-reader
                                                → docs/papers/{slug}.md (논문별 1파일)
  ↓
R-3   /paper-survey (aggregator)                → docs/surveys/paper_survey_v{N}.md
  ↓
R-4   superpowers:verification-before-completion (5+ 논문, 정량 수치, URL, 적용가능성)
  ↓
R-5   /commit-push                              (feature 브랜치)
```

### 두 트랙의 결합

`/deep-analysis`(Step 0.5)는 최근 90일 내 `docs/surveys/paper_survey_v*.md` 존재를 확인하고, 없으면 Research 트랙 선행을 권유한다. `@paper-writer`는 `docs/papers/*.md`와 `docs/surveys/paper_survey_v*.md`를 1차 인용 소스로 사용한다.

## Output Path Mapping

superpowers 기본 산출물 경로(`docs/superpowers/specs/`, `docs/superpowers/plans/`)는 **이 레포에서 사용하지 않는다**. 기존 경로로 매핑:

| superpowers 기본 | 이 레포 사용 경로 | 용도 |
|---|---|---|
| `docs/superpowers/specs/YYYY-MM-DD-*.md` | `docs/plans/experiment_plan_v{N}.md` | brainstorming 산출물(실험 가설·설계) |
| `docs/superpowers/specs/YYYY-MM-DD-*.md` | (Research 트랙은 `docs/surveys/paper_survey_v{N}.md`) | brainstorming 산출물(자료조사 범위) |
| `docs/superpowers/plans/YYYY-MM-DD-*.md` | `docs/plans/review_v{N}.md` | writing-plans 산출물(plan critique) |
| (없음) | `docs/papers/{slug}.md` | paper-reader 산출물 |
| (없음) | `results/analysis_v{N}.md` | verification + 도메인 분석 |

도메인 wrapper(`@experiment-planner`)가 brainstorming/writing-plans 호출 시 prompt에 "Save to ... (override default)"를 명시한다. 기본 경로가 실수로 생성되면 `.gitignore`의 `docs/superpowers/`가 트래킹을 막는다.

## References

- 실험 버전 히스토리 (v1–v8): `docs/experiment-versions.md`
- 실험 환경·설정: `docs/lab-environment.md`

## Rules

상세 규칙은 `rules/` 디렉토리에서 관리:

- **agents.md** — 에이전트 목록, 흡수처 매핑, 오케스트레이션 규칙
- **experiment-pipeline.md** — 실험 7-Step 파이프라인 *(메인 워크트리에서 별도 PR로 갱신 예정)*
- **data-safety.md** — 모델 고정, 데이터 불변, 실험 격리 *(메인 워크트리에서 톤 약화 예정)*
- **lab-workflow.md** — 스킬 카탈로그, Lab 환경 *(메인 워크트리에서 superpowers 통합 갱신 예정)*

## Git Workflow (PR-only 정책)

**모든 워크트리의 수정사항은 반드시 PR을 거쳐 main에 머지**된다. main 브랜치로의 직접 커밋·머지·푸시는 금지.

- 정규 경로: **`superpowers:finishing-a-development-branch`(옵션 2) → `/pr-merge`** 만 사용. feature 브랜치 → push → 한글 PR → 사용자 승인 → `gh pr merge --rebase --delete-branch`.
- **`/commit-push`는 feature 브랜치에서의 중간 커밋 용도**로만 허용. main으로 push하지 않는다.
- PR **제목·본문·커밋 메시지는 한국어**. `--force`, `--no-verify`, `--admin` 머지 전면 금지.
- 강제 수단: `hooks/pr-only-guard.sh`(PreToolUse/Bash)가 main 직접 수정·main push·force·훅 우회를 차단한다. 우회 불가.
