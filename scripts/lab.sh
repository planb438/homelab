#!/usr/bin/env bash
# Usage: lab.sh snapshot <name> | revert <name> | list | stop | start | status
set -euo pipefail
NODES=(cp1 w1 w2)
case "${1:-status}" in
  snapshot) for n in "${NODES[@]}"; do virsh snapshot-create-as "$n" "${2:?name}" --atomic; done ;;
  revert)   for n in "${NODES[@]}"; do virsh snapshot-revert "$n" "${2:?name}"; done ;;
  list)     for n in "${NODES[@]}"; do echo "== $n"; virsh snapshot-list "$n" --name; done ;;
  stop)     for n in w2 w1 cp1; do virsh shutdown "$n" || true; done ;;
  start)    for n in "${NODES[@]}"; do virsh start "$n" || true; done ;;
  status)   virsh list --all ;;
  *) echo "unknown command"; exit 1 ;;
esac
