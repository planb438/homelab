#!/bin/sh
# Copy the synced repo into a writable folder, build the lab config, seed the first admin invite once,
# then run the Worker. Re-copies whenever git-sync pulls a new commit (wrangler reloads by itself).
set -eu
SRC=/git/current WORK=/work/app DATA=/data
case "${STRIPE_SECRET_KEY:-}" in *_live_*) echo "Refusing to start: the lab only accepts a Stripe TEST key (sk_test_/rk_test_)."; exit 1;; esac
mkdir -p "$WORK" "$HOME"

refresh() {
  cp -a "$SRC"/. "$WORK"/ && rm -rf "$WORK/.git"
  node /opt/lab/labconfig.mjs "$WORK"
  printf 'STRIPE_SECRET_KEY=%s\nTEST_TOKEN=%s\n' "${STRIPE_SECRET_KEY:-}" "${TEST_TOKEN:-}" > "$WORK/.dev.vars"
}
refresh
cd "$WORK"

if [ ! -f "$DATA/.seeded" ] && [ -n "${ADMIN_INVITE:-}" ]; then
  now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  wrangler kv key put "invite:${ADMIN_INVITE}" \
    "{\"role\":\"admin\",\"lot_id\":\"\",\"name\":\"Lab admin\",\"note\":\"lab first login\",\"by\":\"lab\",\"created\":\"$now\"}" \
    --binding REQUESTS --local --persist-to "$DATA" -c wrangler.lab.json --ttl 604800
  touch "$DATA/.seeded"
  echo "First admin invite: https://${LAB_HOST:-pc.dev.lab.local}/invite.html?t=${ADMIN_INVITE} (7 days)"
fi

( last=$(readlink -f "$SRC")
  while sleep 60; do
    cur=$(readlink -f "$SRC")
    if [ "$cur" != "$last" ]; then echo "new commit synced -> reloading"; refresh || true; last=$cur; fi
  done ) &

exec wrangler dev -c wrangler.lab.json --persist-to "$DATA" --show-interactive-dev-session=false
