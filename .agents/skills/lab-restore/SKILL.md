---
name: lab-restore
description: thesis-rca fault-injection 실험 후 K8s 리소스, 노드, GitOps, 모니터링과 디스크 상태를 정상화한다. lab-restore, 실험 환경 정상화, 클러스터 정리 요청에만 사용한다.
---

# Lab-restore compatibility wrapper

1. `.claude/skills/lab-restore/SKILL.md`와 `docs/lab-environment.md`를 완전히 읽고 canonical workflow로 실행한다.
2. `/lab-restore`는 `$lab-restore`로, Claude 도구명은 Codex 도구로 번역한다.
3. 이 workflow는 클러스터를 변경하고 데이터를 삭제할 수 있으므로 사용자의 명시적인 실험 재개/복원 지시 범위에서만 실행한다.
4. 명령에 포함된 자격증명은 화면·로그·응답에 출력하지 않는다. 저장소 문서보다 안전한 환경변수나 기존 인증 구성을 우선한다.
5. 원본 `results/` 데이터에는 손대지 않는다. 정확한 대상과 현재 상태를 읽기 전용으로 확인한 뒤 복구하고, 최종 health check 결과로만 정상화를 주장한다.
