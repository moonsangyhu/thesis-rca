---
name: lab-restore
description: 실험 환경 정상화 스킬. 실험 완료 후 "/lab-restore" 또는 "실험 환경 정상화", "클러스터 정리"라고 말할 때 사용. fault injection 잔여물 제거, 리소스 복원, 모니터링 정상화, 디스크 정리 수행.
---

# Lab Restore — 실험 후 환경 정상화

> **Superpowers 흐름 위치**: Experiment 트랙 Step 4 `superpowers:executing-plans`의 마지막 task. 그 다음 `superpowers:verification-before-completion` 게이트가 결과 파일 완성도를 확인한다.

실험(fault injection) 수행 후 클러스터를 원래 상태로 복원한다. `@experiment` wrapper가 실험 완료 후 이 스킬을 호출하여 다음 실험 전 환경을 깨끗하게 만든다.

## 환경 정보

반드시 `docs/lab-environment.md`를 읽어서 최신 인프라 정보를 확인한 뒤 진행한다.

## Workflow

### 1. 현재 클러스터 상태 파악

```bash
export KUBECONFIG=~/.kube/config-k8s-lab

# 노드 상태
kubectl get nodes

# boutique 네임스페이스 pod 상태
kubectl get pods -n boutique

# monitoring 네임스페이스 pod 상태
kubectl get pods -n monitoring --field-selector=status.phase!=Running,status.phase!=Succeeded

# 전체 taint 확인
kubectl get nodes -o custom-columns='NAME:.metadata.name,TAINTS:.spec.taints[*].key'
```

### 2. Fault Injection 잔여물 제거

각 fault type(F1-F10)에 대한 잔여물을 확인하고 복원한다.

#### F1: OOMKilled — 메모리 리밋 복원
```bash
# 비정상적으로 낮은 memory limit 확인
kubectl get deploy -n boutique -o jsonpath='{range .items[*]}{.metadata.name}: {.spec.template.spec.containers[0].resources.limits.memory}{"\n"}{end}'
# 이상 있으면 해당 deployment rollout undo
kubectl rollout undo deploy/DEPLOYMENT -n boutique
```

#### F2: CrashLoopBackOff — 잘못된 command/args 복원
```bash
kubectl get pods -n boutique --field-selector=status.phase!=Running
# CrashLoop 있으면 rollout undo
kubectl rollout undo deploy/DEPLOYMENT -n boutique
```

#### F3: ImagePullBackOff — 이미지 태그 복원
```bash
kubectl get pods -n boutique | grep -E "ImagePull|ErrImage"
# 있으면 rollout undo
kubectl rollout undo deploy/DEPLOYMENT -n boutique
```

#### F4: NodeNotReady — 노드 복구
```bash
kubectl get nodes | grep NotReady
# NotReady 노드가 있으면 해당 Proxmox에서 VM 확인/kubelet 재시작
```

포트 매핑 (Proxmox 포트 → VM IP):
- master01: 22015 → 192.168.100.201
- master02: 22016 → 192.168.100.202
- master03: 22017 → 192.168.100.203
- worker01: 22018 → 192.168.100.211
- worker02: 22019 → 192.168.100.212
- worker03: 22020 → 192.168.100.213

kubelet 재시작 명령:
```bash
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
    -i /Users/yumunsang/Documents/yms-classic-key.pem -p PORT debian@211.62.97.71 \
    "sshpass -p 'Nextktc1!' ssh -o StrictHostKeyChecking=no ktcloud@VM_IP \
    'echo Nextktc1! | sudo -S systemctl restart kubelet'"
```

#### F5: PVC Pending — PVC/PV 정리
```bash
kubectl get pvc -n boutique | grep -v Bound
# Pending PVC가 있으면 삭제 후 재생성
```

#### F6: NetworkPolicy — 차단 정책 제거
```bash
kubectl get networkpolicy -n boutique
# 실험용 NetworkPolicy 삭제
kubectl delete networkpolicy -n boutique -l experiment=true 2>/dev/null || true
```

#### F7: CPU Throttle — CPU limit 복원
```bash
kubectl get deploy -n boutique -o jsonpath='{range .items[*]}{.metadata.name}: {.spec.template.spec.containers[0].resources.limits.cpu}{"\n"}{end}'
# 비정상이면 rollout undo
```

#### F8: Service Endpoint — Service selector 복원
```bash
kubectl get endpoints -n boutique | grep "<none>"
# endpoint가 없는 Service 확인 후 rollout undo
```

#### F9: Secret/ConfigMap — 삭제된 리소스 복원
```bash
kubectl get pods -n boutique | grep -E "CreateContainerConfigError|Error"
# 있으면 rollout undo 또는 GitOps sync
```

#### F10: ResourceQuota — 할당량 제거
```bash
kubectl get resourcequota -n boutique
# 실험용 ResourceQuota 삭제
kubectl delete resourcequota -n boutique -l experiment=true 2>/dev/null || true
```

### 3. 범용 복원: GitOps 동기화

FluxCD/ArgoCD가 설정되어 있으면 동기화로 원상복구:

```bash
# FluxCD reconcile
kubectl annotate gitrepository -n flux-system --all reconcile.fluxcd.io/requestedAt="$(date +%s)" --overwrite 2>/dev/null || true
kubectl annotate kustomization -n flux-system --all reconcile.fluxcd.io/requestedAt="$(date +%s)" --overwrite 2>/dev/null || true

# ArgoCD sync
kubectl exec -n argocd deploy/argocd-server -- argocd app sync boutique --force 2>/dev/null || true
```

### 4. Boutique 앱 정상화 대기

모든 deployment가 Available 상태가 될 때까지 대기:

```bash
# 모든 deployment rollout status 확인
for deploy in $(kubectl get deploy -n boutique -o name); do
    kubectl rollout status $deploy -n boutique --timeout=120s 2>&1
done

# 최종 pod 수 확인 (12개 expected)
kubectl get pods -n boutique --field-selector=status.phase=Running --no-headers | wc -l
```

Running pod가 12개 미만이면 문제 deployment를 식별하고 rollout undo 또는 재시작한다.

### 5. Evicted/Failed Pod 정리

```bash
# 모든 네임스페이스에서 실패한 pod 정리
for ns in boutique monitoring flux-system argocd; do
    kubectl delete pods -n $ns --field-selector=status.phase=Failed 2>/dev/null || true
    kubectl delete pods -n $ns --field-selector=status.phase=Succeeded 2>/dev/null || true
done
```

### 6. 모니터링 스택 정상화

```bash
# Prometheus pod 확인
kubectl get pods -n monitoring -l app.kubernetes.io/name=prometheus

# Loki pod 확인
kubectl get pods -n monitoring -l app.kubernetes.io/name=loki

# Pending이면 disk-pressure 관련 → 디스크 정리 수행 (Step 7)
```

### 7. Worker 노드 디스크 정리 (강화)

모든 Worker 노드에서 디스크 정리 수행. **기본 정리 + Prometheus TSDB 오래된 블록 + 대용량 로그 truncate**:

```bash
# worker01 (22018 → 192.168.100.211)
# worker02 (22019 → 192.168.100.212)
# worker03 (22020 → 192.168.100.213)

for pair in "22018:211" "22019:212" "22020:213"; do
    port="${pair%%:*}"
    ip="${pair#*:}"
    ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
        -i /Users/yumunsang/Documents/yms-classic-key.pem -p $port debian@211.62.97.71 \
        "sshpass -p 'Nextktc1!' ssh -o StrictHostKeyChecking=no ktcloud@192.168.100.$ip \
        'echo Nextktc1! | sudo -S bash -c \"
            # 기본 정리
            crictl rmi --prune 2>/dev/null
            journalctl --vacuum-size=30M 2>/dev/null
            apt-get clean 2>/dev/null
            find /var/log -name \\\\\\\"*.gz\\\\\\\" -delete 2>/dev/null
            find /var/log -name \\\\\\\"*.1\\\\\\\" -delete 2>/dev/null
            find /tmp -type f -mtime +1 -delete 2>/dev/null
            # 대용량 로그 truncate
            truncate -s 0 /var/log/syslog 2>/dev/null
            truncate -s 0 /var/log/kern.log 2>/dev/null
            # Prometheus TSDB 오래된 블록 삭제 (2일 이상)
            find /opt/local-path-provisioner/ -maxdepth 4 -name chunks -type d 2>/dev/null | while read d; do
                parent=\\\\\\\$(dirname \\\\\\\$d)
                mod=\\\\\\\$(stat -c %Y \\\\\\\$parent 2>/dev/null)
                now=\\\\\\\$(date +%s)
                age=\\\\\\\$(( (now - mod) / 86400 ))
                if [ \\\\\\\$age -gt 2 ]; then rm -rf \\\\\\\$parent; echo deleted \\\\\\\$parent; fi
            done
            df -h /
        \"'" 2>/dev/null
done
```

disk-pressure taint가 남아있으면 제거:
```bash
for node in k8s-worker01 k8s-worker02 k8s-worker03; do
    kubectl taint nodes $node node.kubernetes.io/disk-pressure:NoSchedule- 2>/dev/null || true
done
```

DiskPressure condition 확인 — True이면 kubelet 재시작:
```bash
for pair in "22018:211:k8s-worker01" "22019:212:k8s-worker02" "22020:213:k8s-worker03"; do
    port="${pair%%:*}"; rest="${pair#*:}"; ip="${rest%%:*}"; name="${rest#*:}"
    dp=$(kubectl get node $name -o jsonpath='{.status.conditions[?(@.type=="DiskPressure")].status}')
    if [ "$dp" = "True" ]; then
        echo "Restarting kubelet on $name (DiskPressure=True)"
        ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
            -i /Users/yumunsang/Documents/yms-classic-key.pem -p $port debian@211.62.97.71 \
            "sshpass -p 'Nextktc1!' ssh -o StrictHostKeyChecking=no ktcloud@192.168.100.$ip \
            'echo Nextktc1! | sudo -S systemctl restart kubelet'"
    fi
done
sleep 15
```

### 8. Cooldown 대기

클러스터가 안정화될 시간을 확보한다:

```bash
sleep 30
```

### 9. 최종 Health Check

```bash
echo "=== Nodes ==="
kubectl get nodes

echo "=== Node Conditions ==="
kubectl get nodes -o custom-columns='NAME:.metadata.name,READY:.status.conditions[?(@.type=="Ready")].status,DISK:.status.conditions[?(@.type=="DiskPressure")].status,MEM:.status.conditions[?(@.type=="MemoryPressure")].status'

echo "=== Boutique Pods ==="
kubectl get pods -n boutique

echo "=== Monitoring ==="
kubectl get pods -n monitoring --field-selector=status.phase=Running --no-headers | wc -l

echo "=== Prometheus ==="
curl -s http://localhost:9090/-/ready 2>/dev/null || echo "NOT READY (port-forward may need restart)"

echo "=== Loki ==="
curl -s http://localhost:3100/ready 2>/dev/null || echo "NOT READY (port-forward may need restart)"

echo "=== Disk Usage ==="
for pair in "22018:211:worker01" "22019:212:worker02" "22020:213:worker03"; do
    port="${pair%%:*}"; rest="${pair#*:}"; ip="${rest%%:*}"; name="${rest#*:}"
    ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
        -i /Users/yumunsang/Documents/yms-classic-key.pem -p $port debian@211.62.97.71 \
        "sshpass -p 'Nextktc1!' ssh -o StrictHostKeyChecking=no ktcloud@192.168.100.$ip \
        'df / --output=pcent | tail -1'" 2>/dev/null | xargs -I{} echo "$name: {}"
done

echo "=== Experiment Residuals ==="
kubectl get resourcequota -n boutique --no-headers 2>/dev/null | wc -l | xargs -I{} echo "ResourceQuotas: {}"
kubectl get limitrange -n boutique --no-headers 2>/dev/null | wc -l | xargs -I{} echo "LimitRanges: {}"
kubectl get networkpolicy -n boutique --no-headers 2>/dev/null | wc -l | xargs -I{} echo "NetworkPolicies: {}"
```

### 10. 결과 보고

최종 상태를 표로 보여준다:

| 항목 | 상태 | 비고 |
|------|------|------|
| Worker 노드 | N/3 Ready | |
| DiskPressure condition | 모든 노드 False | ⚠️ True이면 실험 불가 |
| Boutique pods | N/12 Running | |
| disk-pressure taint | 있음/없음 | |
| Evicted pods 잔여 | N개 | |
| Prometheus | Ready/Not Ready | |
| Loki | Ready/Not Ready | |
| 디스크 사용률 (worker별) | N% | ⚠️ 75% 이상이면 경고 |
| 실험 잔여물 (quota/policy) | N개 | 0이어야 정상 |

**⚠️ DiskPressure=True 또는 디스크 75% 이상인 노드가 있으면 "실험 환경 미준비" 상태로 보고한다.**

## Rules

- **기존 실험 데이터(`results/`)는 절대 건드리지 않는다**
- fault injection 복원 시 `rollout undo`를 우선 사용 (이전 정상 상태로 돌아감)
- 3회 재시도 후에도 복원 안 되면 사용자에게 보고
- 디스크 정리 시 **Prometheus TSDB 오래된 블록(2일 이상)은 삭제 가능** (최근 데이터는 보존)
- 정상화가 완료되어야 다음 실험 진행 가능
- Prometheus/Loki port-forward가 끊겼으면 재시작 안내 (또는 `/lab-tunnel` 재실행)
