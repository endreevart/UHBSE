#!/bin/sh
# Wait for container-local RoleID + wrapped SecretID, then run Vault Agent (supervisor).
# After Agent/child exit, linger briefly so the host can collect smoke-result.json from tmpfs.
set -eu

RUNTIME=/run/uhbse-vault
mkdir -p "${RUNTIME}/secrets"
chmod 700 "${RUNTIME}" "${RUNTIME}/secrets"

echo "waiting for RoleID and wrapped SecretID in ${RUNTIME}"
i=0
while [ "$i" -lt 120 ]; do
  if [ -f "${RUNTIME}/role-id" ] && [ -f "${RUNTIME}/wrapped-secret-id" ] && [ -f "${RUNTIME}/go" ]; then
    break
  fi
  sleep 0.5
  i=$((i + 1))
done

if [ ! -f "${RUNTIME}/role-id" ] || [ ! -f "${RUNTIME}/wrapped-secret-id" ]; then
  echo "credential files missing" >&2
  exit 1
fi
chmod 600 "${RUNTIME}/role-id" "${RUNTIME}/wrapped-secret-id" || true

date -u +"%Y-%m-%dT%H:%M:%SZ agent_start" > "${RUNTIME}/agent-status.log"

set +e
vault agent -config=/vault/agent/vault-agent.hcl
AGENT_RC=$?
set -e

# Linger so orchestrator can docker exec cat smoke-result.json (tmpfs vanishes on rm).
if [ -f "${RUNTIME}/smoke-result.json" ]; then
  echo "agent exited rc=${AGENT_RC}; lingering for smoke collection"
  sleep 180
else
  echo "agent exited rc=${AGENT_RC}; no smoke-result.json" >&2
  sleep 30
fi
exit "${AGENT_RC}"
