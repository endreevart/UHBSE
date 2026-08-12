# Canonical-loader runtime: Vault Agent (supervisor) + synthetic child in one namespace.
FROM hashicorp/vault:1.17.6

USER root
RUN apk add --no-cache python3 py3-pip \
    && pip3 install --break-system-packages --no-cache-dir 'psycopg[binary]>=3.1' \
    && mkdir -p /usr/local/bin /vault/agent

COPY entrypoint.sh /usr/local/bin/uhbse-runtime-entrypoint
COPY synthetic_child.py /usr/local/bin/uhbse-synthetic-child
COPY vault-agent.hcl /vault/agent/vault-agent.hcl
RUN chmod 755 /usr/local/bin/uhbse-runtime-entrypoint /usr/local/bin/uhbse-synthetic-child \
    && chmod 644 /vault/agent/vault-agent.hcl

ENV VAULT_ADDR=https://vault:8200 \
    VAULT_CACERT=/vault/tls/ca.crt \
    CANONICAL_DB_HOST=canonical-db \
    CANONICAL_DB_PORT=5432 \
    CANONICAL_DB_NAME=uhbse_canonical_dev

ENTRYPOINT ["/usr/local/bin/uhbse-runtime-entrypoint"]
