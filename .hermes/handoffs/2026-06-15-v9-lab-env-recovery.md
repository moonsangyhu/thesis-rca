# 인계 — V9 실험환경 복구: 로컬 복구 완료, 원격 Proxmox 접속 확인 필요

> 새 세션 시작용: 이 파일을 끝까지 읽고 "## 다음 단계" 부터 이어서 진행하세요.

## 한 일
- SSH 설정 문법 오류를 수정했다. `/Users/yumunsang/.ssh/config`의 `Host 211.62.97.71` 블록에서 깨진 `IdentityFile` 줄을 정상화했고, 백업 파일도 생성했다.
- 기존 스크립트가 기대하는 SSH key 경로를 복구했다. `/Users/yumunsang/Documents/yms-classic-key.pem` → `/Users/yumunsang/Documents/문서 - 유문상의 Mac mini/yms-classic-key.pem` symlink를 만들었다.
- Hermes profile HOME 문제를 우회했다. `/Users/yumunsang/.hermes/profiles/lab/home/.kube/config-k8s-lab` → `/Users/yumunsang/.kube/config-k8s-lab` symlink를 만들었다.
- `/Users/yumunsang/thesis-rca/.venv`를 생성하고 `requirements.txt` 의존성을 설치했다. 검증 결과 주요 모듈 missing 없음.
- V9 dry-run을 실행해 로컬 코드 실행성은 확인했다.
  - 명령: `. .venv/bin/activate && python -m experiments.v9.run --dry-run --fault F11 --trial 1 --no-preflight`
  - 결과: `v9 experiment complete! 1/1 trials`
  - 단, 터널이 없어서 metrics/logs/kubectl 수집은 0건이었다.

## 현재 상태
- repo root: `/Users/yumunsang/thesis-rca`
- branch: `setup/hermes-takeover`
- 최근 커밋:
  - `f7f9ef7 setup: Hermes 운영 계약 추가`
  - `2f5cf51 docs(config): Research 트랙 1급화 — Claude 설정 연구 중심 재편`
  - `28dd136 feat(v9): Pre-Trial State Validator + V8 fork — 환경 오염 자동 정정`
- 현재 untracked 파일:
  - `results/experiment_results_v9.csv` — dry-run으로 생성된 header-only CSV, 1 line, 553 bytes. 본실험 데이터 아님.
  - `results/experiment_v9.log` — dry-run 로그, 약 50KB.
- `.venv` 크기 약 1.2G, Python 경로: `/Users/yumunsang/thesis-rca/.venv/bin/python`.
- `ssh -G proxmox-master01`는 성공해서 로컬 SSH config 문법은 정상이다.
- `KUBECONFIG=$HOME/.kube/config-k8s-lab kubectl config view --minify`는 `https://127.0.0.1:6443`, `kubernetes-admin@kubernetes`를 읽는다.
- 하지만 현재 터널은 전부 죽어 있다.
  - K8s API `localhost:6443` — NOT REACHABLE
  - Prometheus `localhost:9090` — NOT REACHABLE
  - Loki `localhost:3100` — NOT REACHABLE
- 원격 공인 IP `211.62.97.71` 접속이 전부 timeout이다.
  - `22015`–`22020`: Timeout
  - `22`, `80`, `443`, `6443`: Timeout
  - `ping`: 100% packet loss
  - `ssh proxmox-master01`: `Operation timed out`

## 다음 단계
- [ ] 집 네트워크에서 `/Users/yumunsang/thesis-rca`로 이동해 `nc -vz -w 5 211.62.97.71 22015`부터 다시 확인한다.
- [ ] `22015`가 열리면 `ssh proxmox-master01 'echo SSH_OK; hostname'`로 SSH 접속을 검증한다.
- [ ] SSH가 되면 `./scripts/tunnel.sh start && ./scripts/tunnel.sh status`를 실행한다.
- [ ] 터널 3개가 OK이면 K8s preflight를 실행한다.
  - `KUBECONFIG=$HOME/.kube/config-k8s-lab kubectl get nodes`
  - `KUBECONFIG=$HOME/.kube/config-k8s-lab kubectl get pods -n boutique`
  - `curl -s http://localhost:9090/-/ready`
  - `curl -s http://localhost:3100/ready`
- [ ] boutique pod, endpoint, worker disk pressure, stale ReplicaSet/CrashLoopBackOff 여부를 확인한다.
- [ ] V9 본실험 전 dry-run artifact 처리 방침을 정한다. `results/experiment_results_v9.csv`는 header-only지만 원본 결과 경로이므로 임의 삭제하지 말고, 실행 직전 백업/초기화 정책을 명확히 한다.
- [ ] preflight가 clean이면 그때 V9 본실험 실행 여부를 결정한다. 지금 상태에서 본실험을 시작하면 안 된다.

## 관련 파일·문서
- `/Users/yumunsang/thesis-rca/AGENTS.md` — Hermes가 이 repo에서 지켜야 할 운영 계약. Experiment Track preflight와 결과 검증 규칙 포함.
- `/Users/yumunsang/thesis-rca/CLAUDE.md` — 현재 Research/Experiment 트랙 구분, V9 대기 상태, 모델 고정 규칙.
- `/Users/yumunsang/thesis-rca/rules/experiment-pipeline.md` — 실험 재개 시 단계별 파이프라인.
- `/Users/yumunsang/thesis-rca/rules/data-safety.md` — 원본 결과 CSV/raw JSON/ground truth 수정 금지.
- `/Users/yumunsang/thesis-rca/docs/lab-environment.md` — K8s lab 접속 정보, 터널 구성, preflight checklist.
- `/Users/yumunsang/thesis-rca/scripts/tunnel.sh` — K8s API/Prometheus/Loki 터널 스크립트.
- `/Users/yumunsang/thesis-rca/experiments/v9/run.py` — V9 실행 엔트리포인트.
- `/Users/yumunsang/thesis-rca/results/experiment_changes_v9.md` — V9 변경 이력과 다음 단계.
- `/Users/yumunsang/.ssh/config` — SSH config 문법 복구됨.
- `/Users/yumunsang/Documents/yms-classic-key.pem` — 실제 key로 향하는 symlink 생성됨.
- `/Users/yumunsang/.hermes/profiles/lab/home/.kube/config-k8s-lab` — 실제 kubeconfig로 향하는 symlink 생성됨.

## 막힌 점 / 결정 대기
- 현재 가장 큰 blocker는 로컬 코드가 아니라 원격 접근성이다. `211.62.97.71` 전체가 timeout이므로 KT Cloud VM/Proxmox 전원, 공인 IP 변경, 보안그룹/firewall, 또는 현재 네트워크 제한을 확인해야 한다.
- V9 dry-run이 `results/experiment_results_v9.csv`와 `results/experiment_v9.log`를 생성했다. 본실험 전 이 artifact를 어떻게 처리할지 결정해야 한다.
- 논문 실험 관점에서 현재 preflight 없는 V9 실행은 금지해야 한다. 지금 돌리면 “StateValidator 효과”가 아니라 “인프라 접속 실패”를 측정하게 된다.

---
생성: 2026-06-15 · 기기: yumunsang-ui-Macmini.local · cwd: /Users/yumunsang/thesis-rca
