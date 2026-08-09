---
name: deep-analysis
description: thesis-rca Experiment Track Step 0.5에서 이전 실험 데이터와 최신 LLM/AIOps 문헌을 깊게 분석해 단일변수 개선 가설을 만든다. deep-analysis, 개선점 분석, 실험 분석 요청에 사용한다.
---

# Deep-analysis compatibility wrapper

1. `.claude/skills/deep-analysis/SKILL.md`를 완전히 읽고 canonical domain workflow로 실행한다.
2. `/deep-analysis`는 `$deep-analysis`로, Claude 도구명은 Codex의 파일·shell·web 도구로 번역한다.
3. 인터넷/문헌 사실은 현재 Codex의 browsing 및 source 규칙에 따라 검증한다. 검색 실패 시 학습 데이터로 논문명·수치를 만들어내지 않는다.
4. `docs/research-charter.md`, 최근 survey, 모든 분석 대상 원본을 실제로 확인한다. CSV는 Python `csv` 모듈로 분석하고 raw JSON 표본 기준을 지킨다.
5. 결과 쓰기 전 데이터·시크릿 가드를 적용하고, 완료 전 실제 검증 결과를 남긴다.
