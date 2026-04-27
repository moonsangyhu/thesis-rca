# 에이전트 & 오케스트레이션 규칙

이 레포는 **superpowers-first**로 운영된다(`CLAUDE.md` 참조). 도메인 에이전트는 superpowers 흐름의 **task 단위 wrapper**로만 존재한다. 역할이 겹치는 에이전트는 superpowers 자산으로 통합되었다.

## 에이전트 목록 (`.claude/agents/`)

| 에이전트 | 역할 | 모델 | superpowers 매핑 |
|---------|------|------|------------------|
| `@experiment-planner` | 실험 가설 수립 wrapper. 이전 결과 분석 + Research 트랙 산출물 인용 | opus | `superpowers:brainstorming` |
| `@experiment` | 실험 실행 wrapper. lab-tunnel → nohup → status → lab-restore 순서 | sonnet | `superpowers:executing-plans` |
| `@paper-writer` | 석사 논문 저술. `docs/papers/`, `docs/surveys/`를 1차 인용 소스로 | opus | (Step 6 외부) 도메인 특화 |

## 흡수된 에이전트 (삭제됨)

기존에 있던 4개 에이전트는 superpowers 자산으로 흡수되었고, 호출 진입점도 변경되었다.

| 삭제된 에이전트 | 흡수처 | 보존 룰 |
|---|---|---|
| `@hypothesis-reviewer` | `superpowers:writing-plans` | plan 문서에 **plan critique 5축**(구성 타당성·내적 타당성·외적 타당성·통계 타당성·대안 가설) 섹션을 강제 포함 |
| `@code-reviewer` | `superpowers:code-reviewer` agent | agent 호출 시 컨텍스트에 **수정 대상 파일 화이트리스트**(예: `experiments/v{N}/`, `src/collector/`, `src/processor/`, `src/llm/`, `src/rag/`) 명시 |
| `@experiment-modifier` | `superpowers:systematic-debugging` | Phase 4(Verify the fix) 직전에 `/changelog` 호출 강제 |
| `@results-writer` | `superpowers:verification-before-completion` + 도메인 분석 Python | Step 5 도메인 분석 snippet은 본 문서 부록 §A 참조 |

`@hypothesis-reviewer` 같은 옛 호칭이 호출되면 오케스트레이터가 위 매핑에 따라 superpowers 스킬로 이행한다.

## 모델 할당 (권장)

- 계획·리뷰·저술(`@experiment-planner`, `@paper-writer`) → **opus**
- 실험 실행(`@experiment`) → **sonnet**

`hooks/agent-model-guard.sh`는 위반 시 **stderr 경고**만 출력하고 통과시킨다(차단 아님). 강제 차단으로 되돌리려면 hook 마지막 줄을 `exit 0` → `exit 2`로 변경.

## 오케스트레이터 역할

1. 새 작업 진입 시 `superpowers:using-superpowers`로 적용 가능한 skill 점검.
2. 창의·설계가 필요하면 `superpowers:brainstorming`부터(HARD-GATE 준수).
3. 도메인 wrapper(`@experiment-planner`, `@experiment`)는 superpowers 스킬 호출의 prompt 보조 역할.
4. **Research 트랙 진입**(`/paper-survey`, `/paper-reader`, `/deep-analysis`)은 1급 도메인 스킬 — `superpowers:brainstorming`으로 범위 확정 후 진입.
5. 단계 완료 시 사용자에게 요약 보고.
6. **실험 전**: `/lab-tunnel`로 터널 + preflight check.
7. **실험 후**: `/lab-restore`로 환경 정상화.
8. 작업 마무리는 `superpowers:finishing-a-development-branch` → `/pr-merge`.

## 공통 규칙

- 코드·문서·설정 수정 후 반드시 `/changelog`로 변경 이력 기록.
- feature 브랜치 중간 커밋은 `/commit-push`. main으로의 push는 절대 금지.
- 작업 최종 완료(=main 반영)는 반드시 `superpowers:finishing-a-development-branch` → `/pr-merge`(한글 PR → 사용자 승인 → rebase 머지). main 직접 커밋·머지·푸시는 `hooks/pr-only-guard.sh`가 차단.
- `superpowers:brainstorming`/`writing-plans` 호출 시 산출물 경로는 `CLAUDE.md`의 *Output Path Mapping*을 따른다(superpowers 기본 경로 무시).

## 부록 §A. Step 5 도메인 분석 snippet (results-writer 흡수)

`superpowers:verification-before-completion` 게이트 통과 후 항상 실행. `results/analysis_v{N}.md`에 작성.

```python
import csv
from collections import defaultdict
from statistics import mean, median

def load(version):
    rows = []
    with open(f"results/experiment_results_{version}.csv") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows

def by_fault_system(rows):
    acc = defaultdict(lambda: defaultdict(list))
    for r in rows:
        acc[r["fault_id"]][r["system"]].append(int(r["correctness_score"]))
    return acc

def summarize(version):
    acc = by_fault_system(load(version))
    print(f"# v{version} 분석")
    for fault in sorted(acc):
        for sys in ("A", "B"):
            scores = acc[fault].get(sys, [])
            if scores:
                print(f"{fault} {sys}: n={len(scores)} acc={mean(scores):.2f} median={median(scores):.1f}")
```

비교 분석(이전 버전 vs 현재 버전)·fault type별 성과·System A vs B 차이를 표로 작성. 가설 검증(이번 라운드 가설이 실제로 성공했는지) 섹션 필수.

## 부록 §B. plan critique 5축 (hypothesis-reviewer 흡수)

`superpowers:writing-plans` 산출물(`docs/plans/review_v{N}.md`)은 plan critique 섹션을 반드시 포함:

1. **구성 타당성** — 가설이 측정 가능한가? 독립변수가 정확히 1개인가?
2. **내적 타당성** — 교란 변수(클러스터 상태, 시간대, 모델 비결정성) 통제됐는가?
3. **외적 타당성** — 결과가 다른 fault type / 다른 클러스터로 일반화 가능한가?
4. **통계 타당성** — 표본 크기 충분한가? 검정 방법(Wilcoxon)이 적절한가?
5. **대안 가설** — "왜 다른 메커니즘으로 설명되지 않는가"의 반박 가능성.
