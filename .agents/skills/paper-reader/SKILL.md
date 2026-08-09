---
name: paper-reader
description: 논문 전문을 20년차 cloud SRE 관점으로 심층 분석하고 thesis-rca 적용성을 문서화한다. paper-reader, 논문 읽기, 단일 논문 분석, Research Track R-2 작업에 사용한다.
---

# Paper-reader compatibility wrapper

1. `.claude/skills/paper-reader/SKILL.md`를 처음부터 끝까지 읽고 canonical domain workflow로 실행한다.
2. `/paper-reader`는 `$paper-reader`로 번역한다. WebSearch/WebFetch/Read는 현재 Codex의 web·PDF·파일 도구로 바꾼다.
3. 논문 전문과 표·그림·실험 섹션을 확인한다. URL, DOI/arXiv, 정량 수치와 메타데이터는 1차 출처로 검증한다.
4. 저작권 한도 내에서 짧게 인용하고 대부분은 한국어로 요약한다. 확인하지 못한 내용은 미확인으로 표시한다.
5. scope 승인 gate와 저장소 Research Track 규칙을 지키며 `docs/papers/{slug}.md`에 기록한다.
