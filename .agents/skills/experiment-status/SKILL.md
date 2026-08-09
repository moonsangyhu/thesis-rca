---
name: experiment-status
description: thesis-rca 실험의 PID, 진행률, trial별 System A/B 결과, 로그 오류와 의미를 확인한다. experiment-status, 실험 상황, 실험 진행상황 요청에 사용한다.
---

# Experiment-status compatibility wrapper

1. `.claude/skills/experiment-status/SKILL.md`를 완전히 읽고 canonical workflow로 실행한다.
2. `/experiment-status`는 `$experiment-status`로 번역하고 Claude 도구명은 Codex 도구로 바꾼다.
3. 가장 최근 파일이라고 추정하지 말고 PID·mtime·plan을 교차 확인해 현재 버전을 결정한다.
4. CSV는 반드시 Python `csv` 모듈로 읽고 수정하지 않는다. 상태 점검 때 `$experiment-issues` workflow도 수행한다.
5. 프로세스가 없거나 결과가 불완전하면 그대로 보고하며 완료를 추정하지 않는다.
