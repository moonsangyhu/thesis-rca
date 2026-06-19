# Handoff — 인프라 재구축 완료 → V10 re-baseline (Hermes 오케스트레이션)

**작성**: 2026-06-19 (Claude Code 세션, subordinate)
**수신**: Hermes (orchestrator of record)
**관련**: `docs/plans/infra_rebuild_plan_v1.md`, `docs/lab-environment.md`, memory `infra-rebuild-direct-ubuntu` / `hermes-orchestration-model`

## 1. 완료된 사실 (검증됨)

- **인프라 재구축 완료, PR #15 머지됨.** nested Proxmox 폐기 → KT Cloud Debian 호스트 6대에 K8s 직접 설치(1 master + 5 worker). 노드당 디스크 15G→50G로 disk-pressure 근절.
- **Preflight GREEN (실측)**: 6/6 노드 Ready·DiskPressure False, boutique 12/12 Running, monitoring 12/12, argocd 5/5, Prometheus `/-/ready`=200, Loki `/ready`=200, 디스크 22~26%.
- **스택**: k8s v1.31.14, containerd 1.7.24, Cilium 1.19.3(kube-proxy replacement + endpointRoutes), local-path SC, Flux GitOps + ArgoCD, Online Boutique 12, kube-prometheus-stack + Loki + promtail.
- **접속**: `~/.kube/config-k8s-lab`(server 127.0.0.1:6443) + `./scripts/tunnel.sh start`(SSH -L 6443 via 포트22015, Prometheus 9090, Loki 3100). NOPASSWD sudo 6대 설정됨.
- **Smoke test 통과**: `python -m scripts.run_experiment --fault F1 --trial 1 --dry-run` → 주입→수집→컨텍스트빌드 정상. loki/promtail Flux HelmRelease가 Stalled였던 것 suspend→resume로 복구, 로그 적재 확인(logs 0/2→1/2).
- **OPENAI_API_KEY 설정·검증**: `.env`(gitignore) + `run_experiment.py`에 `load_dotenv()` 배선. auth OK, gpt-4o-mini 접근 확인.

## 2. V10 re-baseline 지시 (사용자 결정)

환경이 근본적으로 바뀌어 **V1~V9 데이터는 새 환경 baseline으로 무효** → "첫 실험부터 다시". 단 **프레임워크 코드(fault F1–F12, System A/B, RAG, run_experiment.py, V9 Pre-Trial State Validator)는 유지, trial 데이터만 새 환경에서 재수집**. 권장 버전 표기 = **V10**(연속 카운터, re-baseline 명시).

## 3. 실행 전 적응 항목 (남음)

1. **`scripts/fault_inject/config.py` WORKER_NODES** = 옛 nested IP(172.25.20.111~113, user ktcloud) → 새 호스트(yms-proxmox-02~06, SSH 포트 22016~22020, user `debian`, NOPASSWD). **F4(NodeNotReady, SSH 기반)에만 영향**; 나머지 fault는 순수 kubectl이라 무관. → bounded Claude sub-agent 작업으로 적합.
2. **실제 fault 검증 미완** — dry-run에서 metrics 1/14(baseline 무주입이라 이상지표 빔). 실제 F1 trial로 fault 하 metrics 채워짐 + LLM RCA 경로 확인 필요. (키 준비됨)
3. **loki HelmRelease 설치 타임아웃** — bootstrap 시 "client rate limiter context deadline"으로 Stalled 재발 가능. helm-controller install timeout/retry 조정 검토.
4. **실험 version 인자** — dry-run이 v2로 잡음. V10으로 명시 실행 필요.

## 4. 운영 모델

Hermes = orchestrator(계획·디스패치·취합·사용자 보고), Claude = sub-agent(bounded task). 실험 실행은 `rules/experiment-pipeline.md` + `rules/data-safety.md` 준수. 모델 `gpt-4o-mini` 고정. 완료 주장은 결과 row count·raw JSON·로그·분석 검증 후에만. 원본 결과 CSV/raw/ground_truth 직접 수정 금지.

## 5. 다음 체크포인트 (바로 실행 가능)

→ Hermes가 V10 re-baseline을 brainstorming(HARD-GATE)으로 착수: 적응 항목 4개 확정 → fault_inject config 갱신(sub-agent) → 실제 F1 1 trial 검증 → 전체 60케이스 campaign 디스패치.
