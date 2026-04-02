# Debugging ResourceQuota Exceeded

## Overview
ResourceQuota limits the aggregate resource consumption per namespace. When a namespace exceeds its quota, new resource creation (pods, PVCs, services) is blocked. This commonly manifests as Deployments unable to scale or new pods failing to create.

## Symptoms
- Events: `forbidden: exceeded quota: <quota-name>, requested: ..., used: ..., limited: ...`
- Deployment/ReplicaSet stuck with 0 available replicas
- HPA unable to scale up
- `kubectl create` or `kubectl apply` returning quota exceeded errors
- Pods not being created despite ReplicaSet showing desired > available

## Diagnostic Commands

```bash
# View all quotas in namespace
kubectl get resourcequota -n <ns>

# Detailed quota usage
kubectl describe resourcequota -n <ns>

# Check specific quota
kubectl describe resourcequota compute-quota -n boutique

# See what's consuming the quota
kubectl get pods -n <ns> -o custom-columns=\
NAME:.metadata.name,\
CPU_REQ:.spec.containers[0].resources.requests.cpu,\
MEM_REQ:.spec.containers[0].resources.requests.memory

# Check LimitRange defaults
kubectl get limitrange -n <ns> -o yaml

# Check events for quota violations
kubectl get events -n <ns> --field-selector reason=FailedCreate --sort-by='.lastTimestamp'

# Check ReplicaSet conditions
kubectl describe rs <replicaset> -n <ns> | grep -A5 "Conditions"
```

## Common Causes

### 1. Quota too restrictive for workload
Namespace quota set lower than sum of all deployment resource requests.

### 2. LimitRange auto-injecting defaults
When pods don't specify resources, LimitRange injects defaults that count against quota.
```bash
kubectl get limitrange -n boutique -o yaml
# Check default/defaultRequest values
```

### 3. Failed pods consuming quota
Terminated/Failed pods still count against pod count quota until garbage collected.
```bash
kubectl get pods -n <ns> --field-selector status.phase=Failed
kubectl delete pods -n <ns> --field-selector status.phase=Failed
```

### 4. PVC count or storage quota
```bash
kubectl describe resourcequota storage-quota -n <ns>
# Check: persistentvolumeclaims, requests.storage
```

## Resolution Steps

1. **Identify the blocking quota**:
   ```bash
   kubectl describe resourcequota -n boutique
   ```

2. **Calculate actual needs**:
   ```bash
   # Sum all pod resource requests
   kubectl get pods -n boutique -o json | python3 -c "
   import sys, json
   pods = json.load(sys.stdin)['items']
   cpu, mem = 0, 0
   for p in pods:
     for c in p['spec'].get('containers', []):
       r = c.get('resources', {}).get('requests', {})
       cpu_str = r.get('cpu', '0')
       cpu += int(cpu_str.replace('m', '')) if 'm' in cpu_str else int(float(cpu_str) * 1000)
       mem_str = r.get('memory', '0')
       if 'Gi' in mem_str: mem += int(mem_str.replace('Gi','')) * 1024
       elif 'Mi' in mem_str: mem += int(mem_str.replace('Mi',''))
   print(f'Total CPU requests: {cpu}m')
   print(f'Total Memory requests: {mem}Mi')
   "
   ```

3. **Update quota via GitOps**:
   ```yaml
   apiVersion: v1
   kind: ResourceQuota
   metadata:
     name: compute-quota
     namespace: boutique
   spec:
     hard:
       requests.cpu: "8"        # increase from 4
       requests.memory: "16Gi"  # increase from 8Gi
       limits.cpu: "16"
       limits.memory: "32Gi"
       pods: "50"
   ```

4. **Clean up failed/completed pods**:
   ```bash
   kubectl delete pods -n boutique --field-selector status.phase=Failed
   kubectl delete pods -n boutique --field-selector status.phase=Succeeded
   ```

## Prevention
- Set quotas with 30% headroom above normal usage
- Monitor quota utilization:
  ```promql
  kube_resourcequota{type="used"} / kube_resourcequota{type="hard"} > 0.8
  ```
- Always set resource requests/limits to make quota accounting predictable
- Use LimitRange to set sensible defaults
- Include quota manifests in GitOps alongside application manifests

## Related Issues
- [Resource Limits Missing](../known-issues/resource-limits-missing.md)
- [Pod Pending](pod-pending.md)
