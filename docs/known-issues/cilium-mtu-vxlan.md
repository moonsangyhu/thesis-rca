# Known Issue: Cilium VXLAN MTU Mismatch

## Issue ID
KI-001

## Affected Components
- Cilium CNI (v1.15.6, VXLAN mode)
- All pods performing large-payload network transfers
- TCP connections traversing VXLAN tunnels

## Symptoms
- Connection reset (RST) or timeout for HTTP requests with large bodies (>~1450 bytes payload)
- `curl` to services succeeds for small responses but fails for large ones
- `ping` works fine but `scp` or file upload fails
- `kubectl exec` hangs or drops after initial handshake
- Intermittent pod-to-pod communication failures not reproducible with small packets

## Root Cause
Cilium in VXLAN mode adds 50 bytes of encapsulation overhead to every packet (VXLAN header: 8 bytes UDP + 8 bytes VXLAN + 14 bytes Ethernet inner = ~50 bytes total). When the physical NIC MTU is 1500 bytes, the effective MTU for pod traffic must be 1500 - 50 = 1450 bytes.

If Cilium is configured with `mtu: "1500"` (or auto-detected MTU equals the physical MTU), pods attempt to send frames of up to 1500 bytes. These frames cannot be fragmented post-encapsulation by default (DF bit is set), causing the encapsulated packet to exceed the physical MTU and be silently dropped by the underlying network. TCP retransmission eventually gives up and resets the connection.

In this cluster, the physical interface MTU was confirmed at 1500 bytes:
```
eth0: mtu 1500
```

The Cilium ConfigMap `cilium-config` initially did not set an explicit `mtu` value, so Cilium auto-detected 1500 bytes as the pod MTU, failing to account for VXLAN overhead.

## Diagnostic Commands
```bash
# Check current Cilium MTU configuration
kubectl -n kube-system get configmap cilium-config -o yaml | grep -i mtu

# Check physical NIC MTU on a node
ssh worker01 ip link show eth0

# Verify Cilium agent's detected MTU
kubectl -n kube-system exec -it ds/cilium -- cilium status | grep MTU

# Reproduce the issue: test large payload transfer between pods
kubectl run test-sender --image=nicolaka/netshoot --rm -it -- \
  curl -v http://<target-svc>/ --data "$(python3 -c 'print("x"*2000)')"

# Check for ICMP Fragmentation Needed messages (type 3, code 4)
kubectl -n kube-system exec -it ds/cilium -- \
  tcpdump -i any icmp and 'icmp[0]==3 and icmp[1]==4'

# Check for TCP retransmissions on a node
ss -s
```

## Resolution
This issue was resolved in this cluster by explicitly setting the MTU in the Cilium ConfigMap and restarting the DaemonSet.

**Step 1**: Edit the `cilium-config` ConfigMap in `kube-system`:
```bash
kubectl -n kube-system edit configmap cilium-config
```

Add or update the following field:
```yaml
data:
  mtu: "1450"
```

**Step 2**: Restart the Cilium DaemonSet to apply the new MTU:
```bash
kubectl -n kube-system rollout restart daemonset/cilium
kubectl -n kube-system rollout status daemonset/cilium
```

**Step 3**: Verify the new MTU is in effect:
```bash
kubectl -n kube-system exec -it ds/cilium -- cilium status | grep MTU
# Expected: MTU: 1450
```

**Step 4**: Verify pod network interface MTU inside a running pod:
```bash
kubectl exec -it <any-pod> -- ip link show eth0
# Expected: mtu 1450
```

## Workaround
If restarting the DaemonSet is not immediately possible, enable jumbo frames on the physical network (MTU 9000) as a temporary measure. This requires coordination with the hypervisor/network team. Alternatively, reduce TCP MSS via iptables:
```bash
# Apply on each node (not persistent across reboots)
iptables -t mangle -A POSTROUTING -p tcp --tcp-flags SYN,RST SYN \
  -j TCPMSS --set-mss 1410
```

## Prevention
- Always explicitly set `mtu` in `cilium-config` when using VXLAN: `mtu = physical_MTU - 50`
- For Geneve encapsulation: `mtu = physical_MTU - 60`
- Add MTU check to cluster provisioning runbook
- Consider enabling jumbo frames (MTU 9000) on the physical/virtual network to provide headroom

## References
- Cilium docs: https://docs.cilium.io/en/stable/network/concepts/mtu/
- Cilium VXLAN overhead: https://docs.cilium.io/en/stable/network/concepts/routing/
- Upstream issue: https://github.com/cilium/cilium/issues/14740
