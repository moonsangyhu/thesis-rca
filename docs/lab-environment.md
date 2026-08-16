# K8s Lab 실험 환경

> **2026-06-19 재구축**: 기존 nested Proxmox 구조(KT Cloud VM=Proxmox 호스트 위에 K8s VM nested, 디스크 15G)가 만성 disk-pressure(V8/V9 환경 오염)의 근원이라, **Proxmox/nested 층을 폐기하고 KT Cloud Debian 호스트 6대에 K8s를 직접 설치**했다. 노드당 디스크 15G→**50G**. 상세 경위·계획은 `docs/plans/infra_rebuild_plan_v1.md`.

## 인프라 개요

KT Cloud VM 6대(Debian 13 trixie)에 **K8s를 직접** 설치. master 1 + worker 5.

```
[Mac (로컬)] ──SSH(점프)──▶ [KT Cloud Debian 호스트 = K8s 노드]
                            211.62.97.71 : 포트 22015-22020
```

## 네트워크 / 노드 구성

### 외부 접속 (Mac → 호스트)

- 공인 IP: `211.62.97.71`, SSH User: `debian`, Key: `/Users/yumunsang/Documents/yms-classic-key.pem`
- 각 호스트는 `debian` 유저 **NOPASSWD sudo** 설정됨(`/etc/sudoers.d/99-debian-nopasswd`).

| 호스트 | SSH포트 | CPU/RAM/Disk | K8s 역할 | 노드 IP (vmbr0) |
|--------|---------|--------------|----------|------------------|
| yms-proxmox-01 | 22015 | 4c/8GB/50G | **master** (control-plane) | 172.25.100.7 |
| yms-proxmox-02 | 22016 | 4c/8GB/50G | worker | 172.25.100.11 |
| yms-proxmox-03 | 22017 | 4c/8GB/50G | worker | 172.25.100.142 |
| yms-proxmox-04 | 22018 | 8c/16GB/50G | worker | 172.25.100.57 |
| yms-proxmox-05 | 22019 | 8c/16GB/50G | worker | 172.25.100.105 |
| yms-proxmox-06 | 22020 | 8c/16GB/50G | worker | 172.25.100.37 |

### K8s 클러스터 네트워크

| 항목 | 값 |
|------|-----|
| 노드망 | 172.25.100.0/24 (vmbr0) |
| Pod CIDR | 10.244.0.0/16 |
| Service CIDR | 10.96.0.0/12 |
| K8s Version | **v1.31.14** (kubeadm) |
| Container Runtime | containerd 1.7.24 (SystemdCgroup) |
| CNI | **Cilium 1.19.3** (kube-proxy replacement + endpointRoutes) |
| StorageClass | local-path (Rancher, default) |
| GitOps | Flux v2.3.0 + ArgoCD |

### F4 trial 3 node-memory prerequisite

- `yms-proxmox-04`에는 Debian package `stress-ng=0.19.02-1`이 필요하다.
- V2.3은 percentage 기반 할당을 사용하지 않는다. 이 노드의 16 GiB 형상에서
  `--vm 1 --vm-bytes 15G --vm-keep --timeout 180s`를 사용한다. 설치된
  `stress-ng=0.19.02-1`의 `--vm-bytes`는 worker별 할당량이므로 worker 수를
  1로 고정해 총 요청량과 receipt의 15 GiB 의미를 일치시킨다. F4 trial 3은
  40–120초 bounded observation window를 2초 간격으로 확인하고 최초
  `Ready!=True`를 latch한다. 120초까지 관측되지 않으면 fail-closed한다. runner는
  trial 3의 named-node 조회만 5초로 제한하고 timeout/not-observed poll을
  event journal에 기록한다. Node kind·name·UID·유일한 Ready condition이
  정확하지 않은 빈/오염 응답은 retry하지 않고 즉시 거부한다. receipt node도
  shared `yms-proxmox-04` 정본과 일치해야 load/SSH를 시작한다.
  injection 시작부터 full collector 종료까지 monotonic elapsed가 175초 미만인지
  검증해 stressor deadline 안에서 evidence snapshot이 끝난 경우만 inference한다.
  이후 36회 모델 호출 중 자율 종료시켜 SSH exact recovery 여유를 확보한다.
  PID·start tick·cmdline hash receipt와
  실제 `Ready!=True`를 필수로 검증한다. `MemoryPressure`는 보조 관측값일
  뿐 처치 성립을 대신하지 않는다.
- 2026-08-16 model-free 15 GiB·stress timeout 180초·observation deadline 120초
  calibrations 2회는 각각 45.079초와
  65.334초에 `Ready=False`와 live process identity를 만들었고 full collector는
  46.475초와 66.833초에 끝났다. 따라서 변동 onset을 포함하는 위 bounded
  window를 사용하며, stress 180초와 evidence deadline 175초는 유지한다.
- binary 또는 launch receipt가 없으면 모델 호출 전에 fail-closed한다.
- launch identity(PID·start tick·cmdline hash)는 worker03의 mode-0600 임시 파일을
  fsync한 뒤 atomic rename한다. emergency recovery는 이 node-local receipt를
  사용하며, receipt가 없으면 stress process 부재를 확인하기 전 GREEN이 아니다.

## 네임스페이스 / 주요 서비스

| 네임스페이스 | 서비스 | 비고 |
|-------------|--------|------|
| boutique | Online Boutique 마이크로서비스 12개 | |
| monitoring | kube-prometheus-stack(Prometheus 9090, Grafana), Loki(3100), promtail | Flux HelmRelease |
| argocd | argocd-server 등 | Flux HelmRelease |
| flux-system | source/kustomize/helm/notification controller | GitOps 엔진 |
| kube-system | Cilium, coredns | |

## 로컬 접속 방법

### Kubeconfig (`~/.kube/config-k8s-lab`)

- server: `https://127.0.0.1:6443` (SSH 터널 경유, cert SAN에 127.0.0.1 포함)
- `insecure-skip-tls-verify` 불필요(SAN 포함).

### 터널링

```bash
./scripts/tunnel.sh start    # K8s API(6443) + Prometheus(9090) + Loki(3100)
./scripts/tunnel.sh stop
./scripts/tunnel.sh status
```

- K8s API: SSH -L `localhost:6443` → master 호스트(22015)의 `127.0.0.1:6443` (nested 홉 없음)
- Prometheus: `kubectl port-forward svc/kube-prometheus-stack-prometheus 9090`
- Loki: `kubectl port-forward svc/loki 3100`

## 재구축 절차 (kubeadm, 재현용)

`docs/plans/infra_rebuild_plan_v1.md`의 Phase 0~8. 핵심 노드 준비는 `/tmp/k8s-node-prep.sh` 패턴 참조. **Debian 13 trixie 특유의 함정 5가지**(아래)를 반드시 처리해야 한다.

## 알려진 이슈 및 대응 (Debian 13 trixie / kernel 6.17-pve 특이사항)

1. **Proxmox enterprise apt repo 401** → `pve-enterprise.sources`/`pve-install-repo.list` 비활성화(`.disabled`).
2. **k8s apt repo 서명 거부** — trixie의 Sequoia(`sqv`)가 pkgs.k8s.io의 v3 서명 패킷을 거부(2026-02-01 이후). → `/etc/crypto-policies/back-ends/sequoia.config`에 `[packets]\nsignature.v3 = "always"`(서명 검증은 유지). 키 지문 `DE15B14486CD377B9E876E1A234654DA9A296436`.
3. **containerd CNI bin_dir 불일치** — Debian containerd 기본 `/usr/lib/cni`인데 Cilium은 `/opt/cni/bin`에 설치. → config.toml `bin_dir = "/opt/cni/bin"`.
4. **Cilium 서비스/호스트 라우팅** — kube-proxy(iptables)로는 pod→ClusterIP 불가 + eBPF host-routing에서 same-node host→pod 끊겨 health probe 전멸. → `kubeProxyReplacement=true` + `k8sServiceHost=172.25.100.7,k8sServicePort=6443` + **`endpointRoutes.enabled=true`**. kube-proxy DS 삭제 + 노드 KUBE iptables flush.
5. **containerd 기본 AppArmor 프로파일** — `cri-containerd.apparmor.d`가 kernel 6.17 unix-소켓 중재와 불일치 → AF_UNIX 소켓 차단(nginx/redis/argocd/netty 죽음). → config.toml `disable_apparmor = true` + containerd restart. (seccomp·capability·기타 LSM은 유지)

### Worker 디스크 (이제 여유)

호스트 디스크 50G(이전 nested 15G). 현재 22~26% 사용. disk-pressure 만성화 해소됨. 잔여물 정리는 `/lab-restore` 스킬.

### Docker Hub Rate Limit

`ImagePullBackOff`/`429` 시 quay.io 미러 pull 후 태깅(기존 runbook 동일).
