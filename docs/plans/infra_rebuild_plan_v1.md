# 인프라 재구축 계획 v1 — Proxmox 폐기 → 기존 KT Cloud 호스트에 K8s 직접 설치

> **유형**: 인프라 재구축(실험 버전 v1~v9와 별개). **트랙**: Experiment 보조(환경 준비).
> **상태**: 설계 승인됨 (2026-06-19). 파괴 작업(호스트 wipe) 승인 완료. NOPASSWD sudo 셋업 후 Phase 0 착수.
> **작성일/개정**: 2026-06-19

## 1. 배경 / 문제

- 기존 실험 환경은 **KT Cloud Debian VM(=Proxmox 호스트, 50G 디스크) 위에 K8s VM을 nested(15G 디스크)** 로 얹은 2단 구조였다.
- nested 노드 디스크 15G가 과소 → 만성 `disk-pressure` = V8/V9 "환경 오염 fundamental cause".
- 2026-06-19 점검: master 다운, worker 전부 DiskPressure=True, Prometheus/Loki/Boutique Pending, Completed pod 2,088개 누적.

## 2. 목표 / 핵심 전환

**새 VM 생성이 KT Cloud에서 불가** → 기존 6개 호스트를 재사용한다. nested/Proxmox 층을 **걷어내고(wipe)** 호스트 Debian에 **K8s를 직접** 설치한다. 노드마다 **50G 디스크 + 풀 RAM**(15G→50G, 3.3배)을 확보해 disk-pressure를 근본 완화한 깨끗하고 재현 가능한 환경을 만든다.

**범위 경계 (확정)**: **환경 구축(Preflight Green)까지만**. boutique 12개 Running + Prometheus/Loki Ready 검증으로 종료. **V9 실험 재개는 별도 브랜치**.

## 3. 설계 결정 (사용자 확정)

| 항목 | 결정 | 근거 |
|------|------|------|
| 구조 | **Proxmox/nested 폐기**, 호스트 Debian에 K8s 직접 | 2단 구조 + 15G 디스크가 오염 근원 |
| 노드 소스 | **기존 6개 호스트 전부 재사용** (신규 VM 불가) | KT Cloud VM 생성 차단 |
| 토폴로지 | **1 master + 5 worker** (fallback 없음) | 6대 전부 활용 |
| 접속 방식 | **SSH -L 터널로 master 호스트 6443 직결** (nested 홉 제거로 단순화) | 호스트는 211.62.97.71 점프 뒤 → 공인 6443 직접 노출 안 됨. tunnel.sh 단순화(폐기 아님) |
| CNI | **Cilium** (원본 동일) | 실험 fidelity |
| StorageClass | **local-path-provisioner** | 기존 매니페스트 그대로 |
| 앱/모니터링 | **Flux GitOps** → 레포 `k8s/flux`(PUBLIC, 인증 불필요) | 전 스택 코드 선언됨 |
| K8s 버전 | **v1.29.x** (원본 v1.29.15) | helm chart 호환 |
| sudo | **NOPASSWD sudo** 사전 설정 | 평문 비번 inline은 보안 분류기 차단(실증) |

### 노드 배정 / 접속

| 호스트 | SSH포트 | CPU/RAM/Disk | 역할 | 호스트 IP(기본/추가) |
|--------|---------|--------------|------|------|
| yms-proxmox-01 | 22015 | 4c/8GB/50G | **master** | 172.25.100.7 / 172.25.20.34 |
| yms-proxmox-02 | 22016 | 4c/8GB/50G | worker01 | 172.25.100.11 / 172.25.20.36 |
| yms-proxmox-03 | 22017 | 4c/8GB/50G | worker02 | 172.25.100.142 / 172.25.20.12 |
| yms-proxmox-04 | 22018 | 8c/16GB/50G | worker03 | 172.25.100.57 / 172.25.20.144 |
| yms-proxmox-05 | 22019 | 8c/16GB/50G | worker04 | 172.25.100.105 / 172.25.20.155 |
| yms-proxmox-06 | 22020 | 8c/16GB/50G | worker05 | 172.25.100.37 / 172.25.20.69 |

- 점프: `211.62.97.71`, user `debian`, key `/Users/yumunsang/Documents/yms-classic-key.pem`
- 노드 간 통신 IP(172.25.100.x vs 172.25.20.x)는 Phase 0에서 상호 도달성 확인 후 확정.

## 4. 사전 요구사항

- [ ] **NOPASSWD sudo** — 6개 호스트 `debian` 유저에 설정(사용자가 `!`로 1회 실행). 이게 안 되면 셋업 sudo 명령이 분류기에 차단됨.
- (VM 사양은 이미 고정 — 위 표.)

## 5. 작업 단계 (bite-size)

> 각 Phase 종료마다 검증 후 사용자 보고.

### Phase 0 — Preflight & 노드간 통신
- [ ] 6 호스트 SSH 키 접속 + NOPASSWD sudo 동작 확인
- [ ] 노드 간 내부 IP 상호 도달성 확인(어느 대역으로 K8s 통신할지 확정), egress 확인
- [ ] 현재 점유 자원 파악(`qm list`로 nested VM 식별)

### Phase -A — Wipe (Proxmox/nested 폐기) ⚠️ 파괴
- [ ] 각 호스트의 nested K8s VM `qm stop` → `qm destroy` (디스크·RAM 회수)
- [ ] Proxmox VM 워크로드/autostart 비활성, 호스트 네트워크가 K8s에 간섭 않도록 정리
- [ ] 회수 후 `df -h`로 여유 디스크 확인(목표: 노드당 40G+ free)

### Phase 1 — 공통 노드 준비 (6대 전부)
- [ ] swap off, 커널 모듈(`overlay`,`br_netfilter`), sysctl(bridge-nf, ip_forward)
- [ ] containerd + `SystemdCgroup=true`
- [ ] kubeadm/kubelet/kubectl v1.29.x 설치 + hold

### Phase 2 — Control-plane init (master=01)
- [ ] `kubeadm init` (Cilium 호환 pod-cidr, `--apiserver-cert-extra-sans`에 127.0.0.1 및 접속 IP 포함)
- [ ] admin.conf 회수 → 로컬 `~/.kube/config-k8s-lab` 갱신(server=localhost:6443, SSH -L 터널 경유)

### Phase 3 — CNI
- [ ] Cilium 설치, 통신 확인

### Phase 4 — Worker join (×5)
- [ ] 02~06 join → `kubectl get nodes` 6 Ready, DiskPressure 전부 False

### Phase 5 — Flux 부트스트랩
- [ ] Flux 설치 후 레포 `k8s/flux`(main) 동기화(또는 `gotk-*` apply)
- [ ] reconcile: infrastructure → monitoring → argocd → app

### Phase 6 — 배포 검증
- [ ] local-path SC Ready / monitoring(prometheus,loki,promtail) Running / argocd Running / boutique 12개 Running

### Phase 7 — 도메인 파일 갱신
- [ ] `docs/lab-environment.md` — nested/Proxmox 폐기, 신규 6노드 직접 구조로 재작성
- [ ] `scripts/tunnel.sh` — master 호스트 6443 단일 터널로 단순화
- [ ] `scripts/run_experiment.py` 등 — Prometheus/Loki 접근 경로 점검(NodePort/port-forward)
- [ ] `CLAUDE.md` — stale한 워크트리 설명 갱신

### Phase 8 — Preflight Green (완료 기준)
- [ ] 아래 §6 전 항목 OK

## 6. 완료 검증 기준 (verification-before-completion)
- `kubectl get nodes` → 6/6 Ready, 모든 노드 DiskPressure=False
- `kubectl get pods -n boutique` → 12/12 Running
- Prometheus `/-/ready`, Loki `/ready` 200
- worker 디스크 사용률 < 50%
- 실제 명령 출력 첨부해야 완료 주장 가능

## 7. 리스크 / 대응
- **Docker Hub rate limit** → quay.io 미러 pull 후 태깅(기존 runbook).
- **Cilium ↔ pod-cidr 불일치** → init cidr를 Cilium 기본에 맞춤.
- **TLS SAN 누락** → init `--apiserver-cert-extra-sans`에 127.0.0.1/접속 IP.
- **Proxmox 네트워크 잔재(vmbr 브리지)가 Cilium과 충돌** → wipe 시 정리, Phase 0에서 확인.
- **master 8GB 부족** → control-plane 전용(boutique/monitoring은 worker로) 유지.

## 8. 범위 밖
- V9 실험 60 케이스 실행 — 별도 브랜치.

## 9. Git
- 현 워크트리(유일, `setup/hermes-takeover`)에서 작업. PR-only 정책 → 완료 시 `/pr-merge`로 main 머지.
- 도메인 파일 쓰기: 현 브랜치는 가드 비활성(claude-config 아님)으로 허용.
