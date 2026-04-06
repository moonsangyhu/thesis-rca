#!/usr/bin/env bash
# SSH tunnel to K8s lab cluster via Proxmox jump host
# Usage: ./scripts/tunnel.sh [start|stop|status]
#
# Tunnels:
#   localhost:6443  -> K8s API (via SSH to Proxmox -> 192.168.100.201:6443)
#   localhost:9090  -> Prometheus (kubectl port-forward)
#   localhost:3100  -> Loki (kubectl port-forward)

set -euo pipefail

JUMP_HOST="211.62.97.71"
JUMP_PORT="22015"
JUMP_USER="debian"
JUMP_KEY="/Users/yumunsang/Documents/yms-classic-key.pem"
K8S_MASTER="192.168.100.201"

export KUBECONFIG="${HOME}/.kube/config-k8s-lab"

start_tunnel() {
    stop_tunnel 2>/dev/null || true
    sleep 1

    # 1) SSH tunnel for K8s API
    echo "[1/3] K8s API tunnel (localhost:6443 -> ${K8S_MASTER}:6443)..."
    ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
        -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
        -N -f -L 6443:${K8S_MASTER}:6443 \
        -i "$JUMP_KEY" -p "$JUMP_PORT" "${JUMP_USER}@${JUMP_HOST}"

    # Wait for API tunnel
    echo -n "  Waiting..."
    for i in $(seq 1 10); do
        nc -z 127.0.0.1 6443 2>/dev/null && break
        echo -n "."
        sleep 1
    done
    echo " ready"

    # 2) kubectl port-forward for Prometheus
    echo "[2/3] Prometheus port-forward (localhost:9090)..."
    kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090 > /tmp/pf-prometheus.log 2>&1 &

    # 3) kubectl port-forward for Loki
    echo "[3/3] Loki port-forward (localhost:3100)..."
    kubectl port-forward -n monitoring pod/loki-0 3100:3100 > /tmp/pf-loki.log 2>&1 &

    sleep 5
    echo ""
    status_tunnel
}

stop_tunnel() {
    echo "Stopping tunnels..."

    # Kill kubectl port-forwards
    pkill -f "kubectl port-forward.*9090" 2>/dev/null || true
    pkill -f "kubectl port-forward.*3100" 2>/dev/null || true

    # Kill SSH tunnel
    pkill -f "ssh.*-L 6443:${K8S_MASTER}" 2>/dev/null || true

    echo "Done."
}

status_tunnel() {
    echo "=== Tunnel Status ==="
    for pair in "6443:K8s API" "9090:Prometheus" "3100:Loki"; do
        port="${pair%%:*}"
        name="${pair#*:}"
        if nc -z 127.0.0.1 "$port" 2>/dev/null; then
            echo "  $name (localhost:$port) - OK"
        else
            echo "  $name (localhost:$port) - NOT REACHABLE"
        fi
    done
}

case "${1:-start}" in
    start)  start_tunnel ;;
    stop)   stop_tunnel ;;
    status) status_tunnel ;;
    *)      echo "Usage: $0 [start|stop|status]"; exit 1 ;;
esac
