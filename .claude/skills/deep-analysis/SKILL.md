---
name: deep-analysis
description: 실험 개선점 심층 분석 스킬 (Experiment 트랙 Step 0.5). "/deep-analysis" 또는 "개선점 분석", "실험 분석"이라고 말할 때 사용. 이전 실험 데이터를 깊게 분석하고 LLM/AIOps 기법을 인터넷 서칭하여 구체적인 개선 가설을 도출.
---

# Deep Analysis — 실험 개선점 심층 분석 (Experiment Step 0.5)

> **Experiment 트랙 위치**: **Step 0.5 (이 스킬)** → Step 1 `superpowers:brainstorming`(이 스킬의 산출물이 brainstorming 컨텍스트로 흐름) → Step 2 `superpowers:writing-plans` → ...
>
> **Research 트랙 연동**: 진입 직후 최근 90일 내 `docs/surveys/paper_survey_v*.md`이 존재하는지 확인. 없거나 오래되면 사용자에게 **Research 트랙(`/paper-survey` 또는 R-1 brainstorming) 선행을 권유**한다. WebSearch 부분(섹션 3)은 Research 트랙으로 위임 가능.

이전 실험 결과(CSV, raw JSON, 분석 리포트)를 깊게 분석하고, LLM/AIOps 관련 인터넷 서칭을 참조하여 다음 실험의 구체적 개선 가설을 도출한다.

## 인자

- 실험 버전 번호 (예: `v5`) — 다음 실험 버전
- 선택적: 특정 분석 초점 (예: "evaluator 개선", "약점 fault 집중")

## Workflow

### 1. 이전 실험 데이터 수집

아래 파일을 **모두** 읽고 분석한다:

```
results/experiment_results_v*.csv        # 모든 버전 결과
results/analysis_v*.md                   # 모든 버전 분석 리포트
results/ground_truth.csv                 # 정답 레이블
docs/plans/experiment_plan_v*.md         # 이전 실험 계획서
docs/plans/review_v*.md                  # 이전 가설 리뷰
```

### 2. 심층 데이터 분석 (Python 사용)

Bash로 Python 스크립트를 실행하여 아래 분석을 수행한다:

#### 2-1. Trial-level 오답 패턴 분석
- 각 fault type × trial에서 어떤 오답이 나왔는지 분류
- 오답 유형별 빈도 (예: "DiskPressure 오분류 5회", "Service Endpoint 오분류 3회")
- System A와 B에서 동일한 오답이 나온 비율 (공통 실패 패턴)

#### 2-2. 버전 간 변화 추적
- V1→V2→V3→V4에서 각 fault type의 정확도 변화 추세
- 어떤 변경이 어떤 fault에 효과가 있었는지 매핑
- 퇴행(regression)이 발생한 fault type과 원인 추정

#### 2-3. 컨텍스트 구조 분석 (raw JSON 샘플링)
- 정답 trial vs 오답 trial의 prompt_tokens, context 길이 비교
- 정답 trial에서 어떤 신호가 결정적이었는지 (reasoning 필드 분석)
- 오답 trial에서 LLM이 어떤 신호에 속았는지

#### 2-4. Evaluator 효과 분석
- eval_overall_score와 correctness의 상관관계
- retry 전후 정확도 변화 (어떤 조건에서 retry가 효과적인지)
- should_retry 판정의 정확도

#### 2-5. GitOps 컨텍스트 효과 분석
- System B에서만 정답인 trial 목록 + 해당 trial의 GitOps 컨텍스트 특징
- System B에서 오히려 퇴행한 trial 목록 + GitOps 노이즈 패턴

### 3. LLM/AIOps 기법 인터넷 서칭

WebSearch로 아래 키워드를 검색하여 최신 기법을 참조한다:

```
"LLM root cause analysis" improvement techniques 2024 2025
"chain of thought" diagnosis accuracy improvement
"self-consistency" LLM reasoning voting
"decomposed prompting" multi-step reasoning
"LLM evaluator" self-refinement iterative
"retrieval augmented generation" fault diagnosis
```

각 검색 결과에서:
- 기법명, 보고된 효과(정확도 수치), 적용 조건을 추출
- 우리 실험(K8s RCA, gpt-4o-mini, 10 fault types)에 적용 가능한지 판단

**WebSearch 실패 시**: 검색 없이 진행하되, Claude의 학습 데이터 기반 지식으로 대체. 논문명/연도를 명시하여 참조 가능성을 높인다.

### 4. 개선 가설 도출

분석 결과 + 인터넷 서칭을 종합하여 **개선 가설 후보**를 도출하고 **우선순위를 매긴다**. 가설 수는 2~4개 범위로 유동적.

각 가설은 아래 형식을 따른다:

```markdown
### 가설 {a/b/c}: {가설명}

**변경 변수**: V3에서 정확히 1가지만 변경하는 내용
**근거**: 
- 데이터 근거: 이전 실험에서 관찰된 구체적 패턴 (trial 번호, 수치 포함)
- 문헌 근거: 참조한 기법/논문 (가능한 경우)
**메커니즘**: 이 변경이 왜 성능을 개선하는지 인과 설명
**대상 fault types**: 가장 효과가 클 것으로 예상되는 fault types
**예상 효과**: 구체적 수치 (예: "F1 B: 20% → 40%")
**리스크**: 실패 가능성과 그 이유
**구현 범위**: 수정할 파일과 핵심 변경 내용
```

**가설 도출 원칙:**
1. **단일 변수 변경**: 각 가설은 이전 베이스라인에서 정확히 1가지만 변경
2. **데이터 기반**: 반드시 이전 실험의 구체적 오답 패턴에서 출발
3. **다양성 확보**: 가설들이 서로 다른 개선 축을 다뤄야 함 (예: 프롬프트, 컨텍스트, 하네스)
4. **측정 가능**: 성공/실패를 명확히 판단할 수 있는 기준 포함
5. **우선순위 제시**: 가설별 기대 효과·리스크·비용을 비교하여 권장 순서 제시 (1개씩 순차 실행)

### 5. 결과 문서 작성

`docs/surveys/deep_analysis_v{N}.md`에 아래 형식으로 작성:

```markdown
# 심층 분석: v{N} 실험 설계를 위한 개선점 도출

> 분석일: {날짜}
> 분석 대상: v1-v{N-1} 실험 결과
> 목적: v{N} 실험의 3개 가설 수립을 위한 데이터 기반 근거 확보

## 1. 오답 패턴 분석
(2-1 결과)

## 2. 버전 간 변화 추적
(2-2 결과)

## 3. 컨텍스트 구조 분석
(2-3 결과)

## 4. Evaluator 효과 분석
(2-4 결과)

## 5. GitOps 컨텍스트 효과 분석
(2-5 결과)

## 6. 참조 기법 (인터넷 서칭)
(3 결과)

## 7. 개선 가설 3개
(4 결과 — 가설 a, b, c)

## 8. 요약 및 권장 우선순위
3개 가설의 기대 효과 비교 + 권장 실행 순서
```

### 6. 완료 보고

- 도출된 3개 가설과 핵심 근거를 요약 보고
- `/changelog` 호출
- `/commit-push` 호출

## Rules

- **Python 분석 필수**: 단순 파일 읽기가 아닌, CSV 데이터를 프로그래밍적으로 분석해야 한다
- **raw JSON 샘플링**: 최소 정답 3개 + 오답 3개 trial의 raw 데이터를 읽어 질적 분석 수행
- **가설은 2~4개**: 우선순위와 함께 제시, 1개씩 순차 실행할 수 있도록 독립적으로 설계
- **V3 기준**: 모든 가설의 베이스라인은 V3 (V4 아님)
- WebSearch 실패 시 학습 데이터 기반 지식으로 대체 가능 (명시 필요)
- 결과 문서는 한국어, 기법명/논문명은 영문 유지
