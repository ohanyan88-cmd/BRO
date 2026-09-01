#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID} -ne 0 ]]; then
  echo "ERROR: run as root" >&2
  exit 2
fi
if [[ $# -ne 1 ]]; then
  echo "usage: $0 <expected-40-char-main-sha>" >&2
  exit 2
fi
EXPECTED_SHA="${1,,}"
if [[ ! "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "ERROR: expected SHA must be 40 lowercase hex characters" >&2
  exit 2
fi

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "$ROOT" ]]; then
  echo "ERROR: installer must run from a BRO git checkout" >&2
  exit 2
fi
cd "$ROOT"
ACTUAL_SHA="$(git rev-parse HEAD)"
if [[ "$ACTUAL_SHA" != "$EXPECTED_SHA" ]]; then
  echo "ERROR: checkout SHA $ACTUAL_SHA does not match expected $EXPECTED_SHA" >&2
  exit 2
fi
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "ERROR: tracked working tree is dirty" >&2
  exit 2
fi

git fetch --quiet origin main
REMOTE_MAIN="$(git rev-parse origin/main)"
if [[ "$REMOTE_MAIN" != "$EXPECTED_SHA" ]]; then
  echo "ERROR: expected SHA is not current origin/main ($REMOTE_MAIN)" >&2
  exit 2
fi

if ! id bro >/dev/null 2>&1; then
  useradd --system --home /var/lib/bro --shell /usr/sbin/nologin bro
fi
install -d -o root -g root -m 0755 /opt/bro /opt/bro/releases
install -d -o bro -g bro -m 0750 /var/lib/bro
install -d -o bro -g bro -m 0750 /run/bro
install -d -o root -g bro -m 0750 /etc/bro

RELEASE_DIR="/opt/bro/releases/$EXPECTED_SHA"
if [[ ! -d "$RELEASE_DIR" ]]; then
  install -d -o root -g root -m 0755 "$RELEASE_DIR"
  git archive "$EXPECTED_SHA" | tar -x -C "$RELEASE_DIR"
fi

cat > /etc/bro/bro.release.env <<EOF
BRO_ENVIRONMENT=production
BRO_SERVICE_ID=bro
BRO_INSTANCE_ID=$(hostname)
BRO_SOURCE_REVISION=$EXPECTED_SHA
BRO_DB_PATH=/var/lib/bro/runtime.sqlite3
BRO_LOCK_PATH=/run/bro/primary.lock
BRO_HEARTBEAT_SECONDS=10
EOF
chown root:bro /etc/bro/bro.release.env
chmod 0640 /etc/bro/bro.release.env

if [[ ! -e /etc/bro/bro.env ]]; then
  cat > /etc/bro/bro.env <<'EOF'
# Operator-managed non-secret configuration only.
# Secrets must not be committed or written into deployment evidence.
EOF
  chown root:bro /etc/bro/bro.env
  chmod 0640 /etc/bro/bro.env
fi

ln -sfn "$RELEASE_DIR" /opt/bro/current.new
mv -Tf /opt/bro/current.new /opt/bro/current
install -o root -g root -m 0644 "$RELEASE_DIR/deploy/systemd/bro.service" /etc/systemd/system/bro.service
systemctl daemon-reload
systemctl enable bro.service >/dev/null
systemctl restart bro.service

echo "DEPLOYED_SHA=$EXPECTED_SHA"
echo "ACTIVE_RELEASE=$(readlink -f /opt/bro/current)"
systemctl --no-pager --full status bro.service || true
