---
name: lab-tunnel
description: thesis-rca 실험 전에 K8s API·Prometheus·Loki 연결과 클러스터 preflight를 준비한다. lab-tunnel, 터널 연결, 실험 환경 연결 요청에만 사용한다.
---

# Lab-tunnel compatibility wrapper

1. `.claude/skills/lab-tunnel/SKILL.md`, `docs/lab-environment.md`, `.claude/projects/-Users-yumunsang-Documents-thesis-rca/memory/feedback_tunnel_reuse.md`를 완전히 읽는다.
2. `/lab-tunnel`은 `$lab-tunnel`로, Claude 도구명은 Codex 도구로 번역한다.
3. 먼저 기존 터널의 실제 health를 확인한다. 정상이면 종료·재연결하지 않고 그대로 재사용하며 실패한 연결만 복구한다.
4. 실험은 사용자의 명시적 지시가 있을 때만 준비한다. 자격증명을 출력하지 않고 원본 `results/` 데이터에 손대지 않는다.
5. K8s API, Prometheus, Loki, node conditions, disk, pods, residual resources를 실제 출력으로 검증한 후 결과를 보고한다.
