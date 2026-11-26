#!/usr/bin/env bash
# Secrets for the lab ParkingClub. Makes a read-only deploy key, asks for an OPTIONAL Stripe TEST key,
# and prints your first admin invite link once.     Usage: scripts/seal-parkingclub-lab.sh
set -euo pipefail
out="apps/parkingclub-lab/overlays/dev/sealedsecret.yaml"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
ssh-keygen -q -t ed25519 -N "" -C "homelab pc-lab (read-only)" -f "$tmp/key"
read -r -s -p "Stripe TEST secret key (sk_test_/rk_test_…, or Enter to skip): " stripe; echo
case "$stripe" in *_live_*) echo "That's a LIVE key. The lab only takes test keys."; exit 1;; esac
token="$(openssl rand -hex 12)"; invite="$(openssl rand -hex 18)"
kubectl create secret generic pc-lab-secrets -n dev \
  --from-file=DEPLOY_KEY="$tmp/key" \
  --from-literal=STRIPE_SECRET_KEY="$stripe" \
  --from-literal=TEST_TOKEN="$token" \
  --from-literal=ADMIN_INVITE="$invite" --dry-run=client -o yaml \
  | kubeseal --controller-name sealed-secrets-controller --controller-namespace kube-system -o yaml > "$out"
echo "Wrote $out"
echo
echo "1) Add this READ-ONLY deploy key to planb438/parkingclub-site:"
if command -v gh >/dev/null; then
  echo "   gh repo deploy-key add $tmp/key.pub -R planb438/parkingclub-site -t homelab-pc-lab   (running it now)"
  gh repo deploy-key add "$tmp/key.pub" -R planb438/parkingclub-site -t homelab-pc-lab || echo "   -> add it by hand (below)"
fi
echo "   GitHub > parkingclub-site > Settings > Deploy keys > Add (leave 'Allow write access' OFF):"
cat "$tmp/key.pub"
echo
echo "2) First admin login (one use, 7 days):  https://pc.dev.lab.local/invite.html?t=$invite"
echo "3) Test payments in the lab: open https://pc.dev.lab.local/?test=$token once in your browser"
echo "Then: git add $out && git commit -m 'lab: pc-lab secret' && git push"
