---
name: lab-tunnel
description: K8s 실험 환경 터널링 설정. 사용 시점 - 실험 전 "/lab-tunnel" 또는 "터널 연결", "실험 환경 연결"이라고 말할 때. K8s API, Prometheus, Loki 터널을 열고 preflight check 수행.
---

# Lab Tunnel — 실험 환경 터널링 및 Preflight Check

> **Superpowers 흐름 위치**: Experiment 트랙 Step 4의 `superpowers:executing-plans` 첫 번째 task로 호출된다(`@experiment` wrapper의 task 매핑 참조).

실험 환경(K8s 클러스터)에 접속하기 위한 SSH 터널 + kubectl port-forward를 설정하고, 실험 수행 가능 여부를 점검한다.

## 환경 정보

반드시 `docs/lab-environment.md`를 읽어서 최신 인프라 정보를 확인한 뒤 진행한다.

## Workflow

### 1. 기존 터널 정리

기존에 열려있는 터널이 있으면 먼저 정리한다.

```bash
# 기존 SSH 터널 종료
pkill -f "ssh.*-L 6443:192.168.100.201" 2>/dev/null || true

# 기존 kubectl port-forward 종료
pkill -f "kubectl port-forward.*9090" 2>/dev/null || true
pkill -f "kubectl port-forward.*3100" 2>/dev/null || true

sleep 1
```

### 2. SSH 터널 (K8s API)

```bash
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
    -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
    -N -f -L 6443:192.168.100.201:6443 \
    -i /Users/yumunsang/Documents/yms-classic-key.pem \
    -p 22015 debian@211.62.97.71
```

터널 연결 대기 (최대 10초):
```bash
for i in $(seq 1 10); do
    nc -z 127.0.0.1 6443 2>/dev/null && break
    sleep 1
done
```

### 3. kubectl 연결 확인

```bash
KUBECONFIG=~/.kube/config-k8s-lab kubectl get nodes
```

실패 시: SSH 키 경로, Proxmox 호스트 접근, k8s-master01 VM 상태를 순서대로 확인한다.

### 4. Worker 노드 디스크 + 상태 점검

**4a. Node Condition 확인** (taint뿐 아니라 DiskPressure condition 직접 확인):
```bash
KUBECONFIG=~/.kube/config-k8s-lab kubectl get nodes -o custom-columns='NAME:.metadata.name,READY:.status.conditions[?(@.type=="Ready")].status,DISK:.status.conditions[?(@.type=="DiskPressure")].status,MEM:.status.conditions[?(@.type=="MemoryPressure")].status,TAINTS:.spec.taints[*].key'
```

**4b. 실제 디스크 사용량 확인** (taint 없어도 반드시 수행):
```bash
for pair in "22018:211:worker01" "22019:212:worker02" "22020:213:worker03"; do
    port="${pair%%:*}"; rest="${pair#*:}"; ip="${rest%%:*}"; name="${rest#*:}"
    usage=$(ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
        -i /Users/yumunsang/Documents/yms-classic-key.pem -p $port debian@211.62.97.71 \
        "sshpass -p 'Nextktc1!' ssh -o StrictHostKeyChecking=no ktcloud@192.168.100.$ip \
        'df / --output=pcent | tail -1'" 2>/dev/null | tr -d ' %')
    echo "$name: ${usage}%"
done
```

**⚠️ 디스크 사용률 75% 이상이면 자동 정리 수행** (DiskPressure 예방):

```bash
# proxmox 포트 매핑: worker01=22018/211, worker02=22019/212, worker03=22020/213
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
    -i /Users/yumunsang/Documents/yms-classic-key.pem -p PORT debian@211.62.97.71 \
    "sshpass -p 'Nextktc1!' ssh -o StrictHostKeyChecking=no ktcloud@192.168.100.IP \
    'echo Nextktc1! | sudo -S bash -c \"
        crictl rmi --prune 2>/dev/null
        journalctl --vacuum-size=30M 2>/dev/null
        apt-get clean 2>/dev/null
        truncate -s 0 /var/log/syslog 2>/dev/null
        truncate -s 0 /var/log/kern.log 2>/dev/null
        find /var/log -name \\\\\\\"*.gz\\\\\\\" -delete 2>/dev/null
        find /var/log -name \\\\\\\"*.1\\\\\\\" -delete 2>/dev/null
        find /tmp -type f -mtime +1 -delete 2>/dev/null
        find /opt/local-path-provisioner/ -maxdepth 4 -name chunks -type d 2>/dev/null | while read d; do
            parent=\\\\\\\$(dirname \\\\\\\$d)
            mod=\\\\\\\$(stat -c %Y \\\\\\\$parent 2>/dev/null)
            now=\\\\\\\$(date +%s)
            age=\\\\\\\$(( (now - mod) / 86400 ))
            if [ \\\\\\\$age -gt 2 ]; then rm -rf \\\\\\\$parent; fi
        done
        df -h /
    \"'"
```

`disk-pressure` taint가 있거나 DiskPressure condition=True이면:
1. 위 정리 수행 후
2. taint 수동 제거:
   ```bash
   KUBECONFIG=~/.kube/config-k8s-lab kubectl taint nodes NODE node.kubernetes.io/disk-pressure:NoSchedule-
   ```
3. kubelet 재시작하여 condition 재평가:
   ```bash
   ssh ... 'echo Nextktc1! | sudo -S systemctl restart kubelet'
   ```
4. 30초 대기 후 DiskPressure=False 확인. 실패 시 사용자에게 보고.

### 4c. 이전 실험 잔여물 확인

```bash
# Failed/Evicted pods 정리 (이전 실험의 F10 ResourceQuota 등 잔여물)
KUBECONFIG=~/.kube/config-k8s-lab kubectl delete pods -A --field-selector=status.phase=Failed 2>/dev/null || true

# ResourceQuota, LimitRange, NetworkPolicy 잔여물 제거
KUBECONFIG=~/.kube/config-k8s-lab kubectl delete resourcequota -n boutique -l experiment=true 2>/dev/null || true
KUBECONFIG=~/.kube/config-k8s-lab kubectl delete limitrange -n boutique --all 2>/dev/null || true
KUBECONFIG=~/.kube/config-k8s-lab kubectl delete networkpolicy -n boutique --all 2>/dev/null || true

# Boutique deployment replica 정상화 (모두 1/1)
for deploy in $(KUBECONFIG=~/.kube/config-k8s-lab kubectl get deploy -n boutique -o name); do
    KUBECONFIG=~/.kube/config-k8s-lab kubectl scale $deploy -n boutique --replicas=1 2>/dev/null
done
```

### 5. Prometheus/Loki 상태 확인 및 port-forward

Prometheus, Loki pod가 Running인지 확인:
```bash
KUBECONFIG=~/.kube/config-k8s-lab kubectl get pods -n monitoring \
    -l "app.kubernetes.io/name in (prometheus,loki)" \
    --field-selector=status.phase=Running
```

Pending이면:
- Evicted/Failed pod 정리: `kubectl delete pods -n monitoring --field-selector=status.phase=Failed`
- disk-pressure 해소 후 대기

Running 확인 후 port-forward 시작:
```bash
KUBECONFIG=~/.kube/config-k8s-lab kubectl port-forward -n monitoring \
    svc/kube-prometheus-stack-prometheus 9090:9090 > /tmp/pf-prometheus.log 2>&1 &

KUBECONFIG=~/.kube/config-k8s-lab kubectl port-forward -n monitoring \
    pod/loki-0 3100:3100 > /tmp/pf-loki.log 2>&1 &

sleep 5
```

### 6. Preflight Check (최종 검증)

모든 항목이 통과해야 실험 수행 가능:

```bash
# 1) K8s API
KUBECONFIG=~/.kube/config-k8s-lab kubectl get nodes

# 2) Prometheus
curl -s http://localhost:9090/-/ready

# 3) Loki
curl -s http://localhost:3100/ready

# 4) Boutique 앱
KUBECONFIG=~/.kube/config-k8s-lab kubectl get pods -n boutique --field-selector=status.phase=Running --no-headers | wc -l
# 12개여야 정상
```

### 7. 결과 보고

최종 상태를 표로 보여준다:

| 항목 | 상태 |
|------|------|
| K8s API (localhost:6443) | OK / FAIL |
| Prometheus (localhost:9090) | OK / FAIL |
| Loki (localhost:3100) | OK / FAIL |
| Worker 노드 | N/3 Ready |
| Boutique pods | N/12 Running |
| DiskPressure condition | 모든 노드 False 확인 |
| 디스크 사용률 (worker별) | N% (75% 미만이어야 안전) |
| 실험 잔여물 (quota/policy) | 없음/있음 |

## Rules

- 실패한 항목이 있으면 자동으로 복구를 시도한다 (disk 정리, taint 제거, pod 재생성)
- 3회 시도 후에도 실패하면 사용자에게 보고하고 중단한다
- 기존 실험 데이터(`results/`)는 절대 건드리지 않는다
- 터널링 과정에서 클러스터 설정을 변경하지 않는다
- **디스크 사용률 75% 이상이면 실험 진행 불가** — 자동 정리 수행 후 재확인
- **DiskPressure condition이 True인 노드가 있으면 실험 진행 불가** — 정리 + kubelet 재시작 필수
