---
name: paper-survey
description: 승인된 Research Track 범위에서 AIOps·LLM·K8s RCA 논문을 조사·통합해 정량 근거가 있는 survey를 만든다. paper-survey, 논문 조사, 선행연구, 자료조사 요청에 사용한다.
---

# Paper-survey compatibility wrapper

1. `.claude/skills/paper-survey/SKILL.md`와 `rules/research-pipeline.md`를 완전히 읽고 canonical domain workflow로 실행한다.
2. `/paper-survey`는 `$paper-survey`로, Claude 도구명은 Codex web·파일·shell 도구로 번역한다.
3. 신규 조사는 R-1 scope 승인 전 시작하지 않는다. aggregator 모드는 승인된 scope와 기존 `docs/papers/*.md`만 통합한다.
4. 현재 날짜 기준 기간을 계산하고, 논문 전문/공식 페이지에서 URL·서지·정량 수치를 검증한다. 검색 실패 시 논문이나 수치를 기억으로 보완하지 않는다.
5. 최소 5편, 정량 효과, 출처, thesis-rca 적용 가능성 게이트를 실제로 점검한 뒤 완료를 주장한다.
