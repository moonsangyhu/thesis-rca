# Known Issue: GitOps Drift from Manual kubectl Changes

## Issue ID
KI-023

## Affected Components
- FluxCD Kustomize Controller / Helm Controller
- ArgoCD Application Controller
- All Kubernetes resources managed by GitOps
- Cluster operators performing emergency hotfixes

## Symptoms
- Manual `kubectl` changes (scale, patch, edit) are reverted within 1-10 minutes
- An emergency configuration change is overwritten by the next GitOps reconcile cycle
- Operations team cannot keep a manual fix in place during an incident
- `kubectl edit deployment <name>` changes disappear silently
- `kubectl scale deployment <name> --replicas=0` reverts to configured replica count
- Pod restarts after a manual resource limit increase is reverted by FluxCD
- Discrepancy between what `kubectl get` shows and what Git has — but only briefly, before reverting

## Root Cause
GitOps tools (FluxCD, ArgoCD) continuously reconcile the cluster state with the Git repository. Any deviation from the Git-defined desired state is considered "drift" and is corrected on the next reconcile interval.

**FluxCD** reconciles every `spec.interval` (often 1-10 minutes). Any field owned by a Flux resource is reverted at the next reconcile cycle. This is intentional and correct behavior — it is the core guarantee of GitOps.

**ArgoCD** similarly syncs (automatically or manually triggered) and overwrites manual changes.

The problem is not a bug — it is a fundamental property of GitOps that operators sometimes forget during incidents. Common scenarios:
1. Scaling down a problematic deployment: `kubectl scale --replicas=0` → reverted in 5 minutes
2. Emergency ConfigMap change: `kubectl edit` → overwritten on next reconcile
3. Node label for affinity: manually added label → reverted if node labels are managed by GitOps
4. Secret value change: manually updated → overwritten by External Secrets Operator

## Diagnostic Commands
```bash
# Check FluxCD reconcile interval for a resource
kubectl get kustomization -n flux-system -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.interval}{"\n"}{end}'
kubectl get helmrelease -A -o jsonpath='{range .items[*]}{.metadata.namespace}{"\t"}{.metadata.name}{"\t"}{.spec.interval}{"\n"}{end}'

# Check if a resource is managed by FluxCD
kubectl get deployment <name> -n <namespace> -o yaml | grep -i flux

# Check FluxCD ownership labels/annotations
kubectl get deployment <name> -n <namespace> -o jsonpath='{.metadata.labels}' | jq
# Look for: kustomize.toolkit.fluxcd.io/name or helm.toolkit.fluxcd.io/name

# See when last reconcile happened
kubectl get kustomization <name> -n flux-system -o jsonpath='{.status.lastAppliedRevision}'

# Check ArgoCD ownership
kubectl get deployment <name> -n <namespace> -o yaml | grep argocd

# Monitor for drift correction events
kubectl get events -n <namespace> --watch | grep -i "reconcil\|apply\|revert"

# Check what FluxCD would apply
flux diff kustomization <name> --path ./clusters/k8s-lab
```

## Resolution
**For emergency hotfixes that must survive reconciliation**:

**Method 1: Suspend the GitOps reconciliation (recommended for incidents)**
```bash
# Suspend FluxCD Kustomization
flux suspend kustomization <kustomization-name> -n flux-system

# Make your emergency changes
kubectl scale deployment <name> -n <namespace> --replicas=0
kubectl patch deployment <name> -n <namespace> --type=merge -p '{"spec":{"template":{"spec":{"containers":[{"name":"app","resources":{"limits":{"memory":"1Gi"}}}]}}}}'

# Monitor and resolve the incident

# IMPORTANT: Resume and commit the fix to Git before next business day
flux resume kustomization <kustomization-name> -n flux-system
```

For ArgoCD:
```bash
argocd app set <app-name> --sync-policy none   # Disable auto-sync
# Make emergency changes
argocd app set <app-name> --sync-policy automated  # Re-enable after committing to Git
```

**Method 2: Commit the emergency change to Git immediately**
The correct GitOps approach — even for emergencies — is to commit the change to Git first:
```bash
# Edit the manifest in Git
git checkout -b emergency/scale-down-frontend
# Edit the file
git commit -m "emergency: scale frontend to 0 during incident"
git push origin emergency/scale-down-frontend
# Apply via PR or force-push to main (depending on policy)
flux reconcile kustomization <name> --with-source  # Force immediate reconcile
```

**Method 3**: Use FluxCD's reconciliation annotation to temporarily pause a specific resource:
```bash
# Not natively supported per-resource — must suspend the parent Kustomization
```

**Post-incident**: Always update Git to reflect the correct state, then resume reconciliation:
```bash
# 1. Fix the root cause
# 2. Update Git manifests with correct configuration
# 3. Resume Flux
flux resume kustomization <name> -n flux-system
# 4. Verify the state matches Git
flux diff kustomization <name>
```

## Workaround
Create a separate "emergency" Kustomization with a very long interval (e.g., 24h or suspended) for making urgent manual changes without constant reversion. Keep it clearly documented and never suspended permanently.

## Prevention
- Train all cluster operators on GitOps principles: **all changes go through Git**
- Set up fast-path Git merge (e.g., direct push to main with proper review bypass for SEV1)
- Create runbooks for common emergency operations that include Git commit steps
- Enable Slack/PagerDuty notifications when FluxCD detects and reverts drift
- Use `flux diff` before making changes to understand what will happen
- Document emergency procedures: `fluxcd suspend` → fix → commit → `flux resume`

## References
- FluxCD suspend/resume: https://fluxcd.io/flux/cheatsheets/operations/#suspend-and-resume
- FluxCD drift detection: https://fluxcd.io/flux/components/kustomize/kustomizations/#drift-detection
- GitOps principles: https://opengitops.dev/
- Handling incidents in GitOps: https://www.weave.works/blog/gitops-and-kubernetes-incidents
