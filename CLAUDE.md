# K8s RCA 석사 논문 실험 플랫폼

> 🛡️ 이 워크트리는 **Claude 설정 전용**(`claude-config` 브랜치)입니다. `hooks/claude-config-guard.sh`가 Claude 관련 경로(`.claude/**`, `CLAUDE.md`, `rules/agents.md`, `hooks/claude-config-guard.sh`, `.gitignore`) 외의 Write/Edit/MultiEdit를 차단합니다. 도메인 파일 수정은 메인 워크트리(`/Users/yumunsang/Documents/thesis-rca`, `main` 브랜치)에서 수행하세요.

GitOps 컨텍스트(FluxCD/ArgoCD) 추가 시 LLM 기반 장애 원인 분석 정확도 향상을 검증한다.

- **System A**: Prometheus + Loki + kubectl → LLM
- **System B**: System A + GitOps + RAG → LLM
- 10 fault types (F1–F10) × 5 trials = 50 cases
- **모델 고정**: gpt-4o-mini 고정. 개선은 프레임워크 레벨에서만

문서·프롬프트는 한국어, 코드·변수명은 영어.

## References

- 실험 버전 히스토리 (v1–v5): `docs/experiment-versions.md`
- 실험 환경·설정: `docs/lab-environment.md`

## Rules

상세 규칙은 `rules/` 디렉토리에서 관리:

- **agents.md** — 에이전트 목록, 오케스트레이션 규칙, 토론 프로토콜
- **experiment-pipeline.md** — 1가설 순차 실행 파이프라인 (Step 0.5–5)
- **data-safety.md** — 모델 고정, 데이터 불변, 실험 격리 규칙
- **lab-workflow.md** — 스킬 카탈로그, 실험 워크플로우, Lab 환경

## Git Workflow (PR-only 정책)

**모든 워크트리의 수정사항은 반드시 PR을 거쳐 main에 머지**된다. main 브랜치로의 직접 커밋·머지·푸시는 금지.

- 정규 경로: **`/pr-merge` 스킬**만 사용. feature 브랜치 → push → 한글 PR → 사용자 승인 → `gh pr merge --rebase --delete-branch`.
- **`/commit-push`는 feature 브랜치에서의 중간 커밋 용도**로만 허용. main으로 push하지 않는다.
- PR **제목·본문·커밋 메시지는 한국어**. `--force`, `--no-verify`, `--admin` 머지 전면 금지.
- 강제 수단: `hooks/pr-only-guard.sh`(PreToolUse/Bash)가 main 직접 수정·main push·force·훅 우회를 차단한다. 우회 불가.
