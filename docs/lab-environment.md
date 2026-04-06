# K8s Lab 실험 환경

## 인프라 개요

KT Cloud VM 6대가 Proxmox VE로 클러스터링되어 있고, 각 Proxmox 호스트 위에 K8s VM이 1대씩 구동된다.

```
[Mac (로컬)] ──SSH──▶ [Proxmox 호스트] ──SSH──▶ [K8s VM]
                        211.62.97.71           192.168.100.x
                        (포트 22015-22020)
```

## 네트워크 구성

### 외부 접속 (Mac → Proxmox)

| 포트  | Proxmox 호스트    | 내부 IP (vmbr5)   |
|-------|--------------------|--------------------|
| 22015 | yms-proxmox-01     | 192.168.100.1      |
| 22016 | yms-proxmox-02     | 192.168.100.1      |
| 22017 | yms-proxmox-03     | 192.168.100.1      |
| 22018 | yms-proxmox-04     | 192.168.100.1      |
| 22019 | yms-proxmox-05     | 192.168.100.1      |
| 22020 | yms-proxmox-06     | 192.168.100.1      |

- 공인 IP: `211.62.97.71`
- SSH User: `debian`
- SSH Key: `/Users/yumunsang/Documents/yms-classic-key.pem`

### Proxmox → K8s VM 매핑

각 Proxmox 호스트는 **자신의 VM만** 192.168.100.x (vmbr5) 네트워크로 접근 가능하다.

| Proxmox (포트) | K8s 노드       | VM IP              | K8s 내부 IP (ens19) |
|----------------|----------------|--------------------|----------------------|
| 22015          | k8s-master01   | 192.168.100.201    | 172.25.20.101        |
| 22016          | k8s-master02   | 192.168.100.202    | 172.25.20.102        |
| 22017          | k8s-master03   | 192.168.100.203    | 172.25.20.103        |
| 22018          | k8s-worker01   | 192.168.100.211    | 172.25.20.x          |
| 22019          | k8s-worker02   | 192.168.100.212    | 172.25.20.x          |
| 22020          | k8s-worker03   | 192.168.100.213    | 172.25.20.x          |

- K8s VM User: `ktcloud`
- K8s VM Password: `Nextktc1!`
- sshpass가 각 Proxmox 호스트에 설치됨

### K8s 클러스터 네트워크

| 항목               | 값                        |
|--------------------|---------------------------|
| K8s API VIP        | 172.25.20.200:6443        |
| K8s API (모든 IF)  | *:6443 (0.0.0.0)          |
| Service CIDR       | 10.96.0.0/12              |
| Pod CIDR           | 10.0.0.0/8 (Cilium)       |
| K8s Version        | v1.29.15                  |
| CNI                | Cilium                    |
| StorageClass       | local-path (Rancher)      |

## K8s 클러스터 구성

### 노드

| 노드           | 역할           | CPU | Memory | Disk  |
|----------------|----------------|-----|--------|-------|
| k8s-master01   | control-plane  | 4   | 8Gi    | 15G   |
| k8s-master02   | control-plane  | 4   | 8Gi    | 15G   |
| k8s-master03   | control-plane  | 4   | 8Gi    | 15G   |
| k8s-worker01   | worker         | 4   | 8Gi    | 15G   |
| k8s-worker02   | worker         | 4   | 8Gi    | 15G   |
| k8s-worker03   | worker         | 4   | 8Gi    | 15G   |

### 네임스페이스 및 주요 서비스

| 네임스페이스 | 서비스                                | 포트       |
|-------------|---------------------------------------|------------|
| boutique    | Online Boutique 마이크로서비스 (12개) | 다양       |
| monitoring  | kube-prometheus-stack-prometheus       | 9090       |
| monitoring  | loki                                  | 3100       |
| monitoring  | kube-prometheus-stack-grafana          | 80         |
| monitoring  | promtail (DaemonSet)                  | -          |
| flux-system | FluxCD (source, notification)         | 80         |
| argocd      | argocd-server (NodePort)              | 30080/30443|

## 로컬 접속 방법

### SSH Config (`~/.ssh/config`)

```
Host proxmox-master01
    HostName 211.62.97.71
    Port 22015
    User debian
    IdentityFile /Users/yumunsang/Documents/yms-classic-key.pem
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
    LogLevel ERROR

Host k8s-master01
    HostName 192.168.100.201
    User ktcloud
    ProxyJump proxmox-master01
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
    LogLevel ERROR
```

### Kubeconfig (`~/.kube/config-k8s-lab`)

- server: `https://127.0.0.1:6443` (SSH 터널 경유)
- `insecure-skip-tls-verify: true` (인증서 SAN에 127.0.0.1 미포함)

### 터널링

```bash
# 터널 시작 (K8s API + Prometheus + Loki)
./scripts/tunnel.sh start

# 터널 종료
./scripts/tunnel.sh stop

# 상태 확인
./scripts/tunnel.sh status
```

터널 구성:
1. **K8s API** — SSH 터널: `localhost:6443` → Proxmox-01 → `192.168.100.201:6443`
2. **Prometheus** — kubectl port-forward: `localhost:9090` → `svc/kube-prometheus-stack-prometheus:9090`
3. **Loki** — kubectl port-forward: `localhost:3100` → `pod/loki-0:3100`

## 알려진 이슈 및 대응

### Worker 노드 디스크 부족 (disk-pressure)

Worker 노드 디스크가 15G로 작아서 disk-pressure가 빈번하게 발생한다.

**증상:** Pod가 Evicted/Pending, `node.kubernetes.io/disk-pressure:NoSchedule` taint 발생

**대응:**
```bash
# 각 Worker 노드에서 정리 (proxmox 포트 / VM IP 맞춰서)
ssh -i KEY -p PORT debian@211.62.97.71 \
  "sshpass -p 'Nextktc1!' ssh ktcloud@VM_IP \
  'echo Nextktc1! | sudo -S bash -c \"
    crictl rmi --prune
    journalctl --vacuum-size=50M
    apt-get clean
    find /var/log -name \\\"*.gz\\\" -delete
    find /var/log -name \\\"*.1\\\" -delete
  \"'"

# taint 자동 제거 안 되면 수동 제거
kubectl taint nodes NODE node.kubernetes.io/disk-pressure:NoSchedule-

# kubelet 재시작으로 상태 갱신
# (VM에서) sudo systemctl restart kubelet
```

### Docker Hub Rate Limit

**증상:** `ImagePullBackOff`, `429 Too Many Requests`

**대응:**
```bash
# quay.io 미러에서 pull 후 태깅
crictl pull quay.io/IMAGE:TAG
ctr -n k8s.io images tag quay.io/IMAGE:TAG docker.io/IMAGE:TAG
```

### Evicted/Failed Pod 정리

```bash
kubectl delete pods -n NAMESPACE --field-selector=status.phase=Failed
kubectl delete pods -n NAMESPACE --field-selector=status.phase=Succeeded
```

## 실험 Preflight Checklist

1. `./scripts/tunnel.sh status` — 터널 3개 모두 OK
2. `kubectl get nodes` — Worker 노드 3개 Ready
3. `kubectl get pods -n boutique` — 12개 Pod Running
4. `curl -s http://localhost:9090/-/ready` — Prometheus Ready
5. `curl -s http://localhost:3100/ready` — Loki Ready
6. Worker 디스크 사용량 < 80%
