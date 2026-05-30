# Research 파이프라인 — 선행연구 자료조사 (현재 본류)

사용자가 "논문 조사", "선행연구 조사", "자료조사" 등 자료조사를 지시하면 **반드시 아래 R-1~R-5를 순서대로** 실행한다. 이 트랙은 superpowers-first 원칙을 그대로 따르며, 각 단계는 superpowers 스킬 또는 도메인 스킬의 task 단위다.

이 레포의 **현재 본류 트랙**이다. Experiment 트랙(`rules/experiment-pipeline.md`)은 보조이며 V9 실행 대기 상태다.

## 파이프라인

```
R-0: superpowers:using-superpowers   →  세션 진입 시 적용 가능한 skill 인지
                                   ⬇
R-1: @research-planner               →  자료조사 범위 확정 (superpowers:brainstorming wrapper)
         - 입력: 위키(~/ms/wiki/) 탑다운 + 기존 docs/surveys/*, docs/papers/* + 이전 실험 결과(포지셔닝 공백)
         - brainstorming 5문항 캡: 키워드 / 기간·DB / 범위 / 포지셔닝 각 / 논문 기여 적용성
         - HARD-GATE: scope 승인 전 검색 금지
         - 산출물: docs/surveys/research_scope_v{N}.md
                                   ⬇
R-2: superpowers:dispatching-parallel-agents  →  키워드 N개 → N개 sub-agent 병렬
         - 각 sub-agent: WebSearch + /paper-reader (20년차 SRE 관점 심층 읽기)
         - 산출물: docs/papers/{slug}.md (논문별 1파일)
                                   ⬇
R-3: /paper-survey (aggregator)      →  논문별 파일을 종합
         - 최근 3년 AIOps+LLM 성능 개선 기법 종합, 기법별 정량 효과 표
         - 산출물: docs/surveys/paper_survey_v{N}.md
                                   ⬇
R-4: superpowers:verification-before-completion  →  완료 게이트
         - 검증: 5+ 논문, 각 논문 정량 수치·URL, 본 논문에의 적용가능성 명시
                                   ⬇
R-5: superpowers:finishing-a-development-branch → /pr-merge
         - 중간 커밋은 /commit-push (feature 브랜치). main 직접 push 금지.
```

## 산출물 경로

| 산출물 | 경로 | 생성 단계 |
|-------|------|----------|
| 자료조사 범위 | `docs/surveys/research_scope_v{N}.md` | R-1 |
| 논문별 분석 | `docs/papers/{slug}.md` | R-2 |
| 종합 서베이 | `docs/surveys/paper_survey_v{N}.md` | R-3 |

## 심층 단일 주제 조사 (대안)

특정 주제 1개를 다출처·교차검증으로 깊게 파야 할 때는 전역 `/deep-research` 스킬을 R-2 대체로 사용할 수 있다. 산출물은 동일하게 `docs/surveys/` 또는 `docs/papers/`로 정리한다.

## Experiment 트랙과의 결합

Research 트랙 산출물(`docs/surveys/paper_survey_v*.md`, `docs/papers/*.md`)은 Experiment 트랙의 1차 인용 소스다.

- `@experiment-planner`(Experiment Step 1)는 최근 90일 내 `paper_survey_v*.md`를 입력으로 요구한다.
- `/deep-analysis`(Experiment Step 0.5)는 해당 survey가 없으면 Research 트랙 선행을 권유한다.
- `@paper-writer`는 `docs/papers/*.md` + `docs/surveys/paper_survey_v*.md`를 1차 인용 소스로 사용한다.

## 위키 연동

자료조사 입력·정리는 업무 위키(`~/ms/wiki/`)와 연동한다(전역 CLAUDE.md "개인 위키 — 탑다운 조회 규칙" 준수).

- 입력 수집: `wiki/moonsang.md`(허브) → `concepts/`·`sources/` 탑다운 탐색. `raw/` 직행 금지.
- 관련 핵심 페이지 예: `[[LLM 기반 RCA]]`, `[[LLM U-shape 주의 편향]]`, `[[thesis-rca]]`, `sources/*-LLM 기반 RCA 연구 동향`.
- 위키 수정은 사용자 명시 지시가 있을 때만.

## 공통 규칙

- 작업 완료 후 `/changelog`로 변경 이력 기록.
- 중간 커밋은 `/commit-push`(feature 브랜치). 최종 반영은 `superpowers:finishing-a-development-branch` → `/pr-merge`. main 직접 커밋·머지·푸시 금지(`hooks/pr-only-guard.sh`).
- 산출물 경로는 `CLAUDE.md`의 *Output Path Mapping*을 따른다.
