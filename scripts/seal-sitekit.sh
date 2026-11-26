#!/usr/bin/env bash
# Make the sealed secret for one lab site. Prints the first admin password ONCE — save it in your password manager.
# Usage: scripts/seal-sitekit.sh <cloudkanata|askcanada|acb|hub> <env> <admin-email> [launcher.json]
set -euo pipefail
site="${1:?site}"; env="${2:?env (dev)}"; email="${3:?admin email}"; launcher="${4:-}"
case "$site" in cloudkanata) p=ck;; askcanada) p=ask;; acb) p=acb;; hub) p=hub;; *) echo "unknown site"; exit 1;; esac
out="apps/site-${site}/overlays/${env}/sealedsecret.yaml"
name="${p}-sitekit-secrets"
pw="$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-20)"
args=(--from-literal=POSTGRES_PASSWORD="$(openssl rand -hex 24)"
      --from-literal=SECRET_KEY="$(openssl rand -hex 32)"
      --from-literal=ADMIN_EMAIL="$email"
      --from-literal=ADMIN_PASSWORD="$pw")
[ -n "$launcher" ] && args+=(--from-literal=LAUNCHER="$(tr -d '\n' < "$launcher")")
kubectl create secret generic "$name" -n "$env" "${args[@]}" --dry-run=client -o yaml \
  | kubeseal --controller-name sealed-secrets-controller --controller-namespace kube-system -o yaml \
  | sed "0,/^  name: ${name}\$/s//  name: sitekit-secrets/" > "$out"   # kustomize adds the "${p}-" prefix back
echo "Wrote $out"
echo "Admin login for $site ($env): $email  /  $pw   <- shown once"
echo "Note: the admin is only created when the database is empty (first start)."
