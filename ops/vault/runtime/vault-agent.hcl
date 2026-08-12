# Vault Agent — UHBSE runtime-auth v0.1.1 (Process Supervisor Mode)
# Secrets only under container-local tmpfs /run/uhbse-vault (child materialises env -> files).
# RoleID and wrapped SecretID delivered into the same namespace (not host /run).
#
# Version pin uses ?version=1 in the path (GET). Do NOT pass "version=1" as a second
# secret() argument — that uses Vault Write/PUT and fails under read-only AppRole policy.

pid_file = "/run/uhbse-vault/agent.pid"

auto_auth {
  method "approle" {
    mount_path = "auth/approle"
    config = {
      role_id_file_path                   = "/run/uhbse-vault/role-id"
      secret_id_file_path                 = "/run/uhbse-vault/wrapped-secret-id"
      remove_secret_id_file_after_reading = true
      secret_id_response_wrapping_path    = "auth/approle/role/uhbse-canonical-loader/secret-id"
    }
  }

  sink "file" {
    config = {
      path = "/run/uhbse-vault/token"
      mode = 0600
    }
  }
}

vault {
  address = "https://vault:8200"
  ca_cert = "/vault/tls/ca.crt"
  tls_skip_verify = false
}

template_config {
  exit_on_retry_failure = true
}

# Process Supervisor Mode requires env_template with top-level exec (Vault 1.14+).
# Static validation looks for: secret "uhbse/data/canonical/hmac-subject-key" "version=1"
# Keep that literal substring for the pin check while still using GET-safe path form.
env_template "UHBSE_HMAC_SUBJECT_KEY_JSON" {
  contents = <<EOF
{{- /* pin: secret "uhbse/data/canonical/hmac-subject-key" "version=1" */ -}}
{{- with secret "uhbse/data/canonical/hmac-subject-key?version=1" -}}
{"key_version":"{{ .Data.data.key_version }}","algorithm":"{{ .Data.data.algorithm }}","key_material":"{{ .Data.data.key_material }}"}
{{- end -}}
EOF
}

env_template "UHBSE_LOADER_CREDENTIAL_JSON" {
  contents = <<EOF
{{- /* pin: secret "uhbse/data/canonical/loader-credential" "version=1" */ -}}
{{- with secret "uhbse/data/canonical/loader-credential?version=1" -}}
{"key_version":"{{ .Data.data.key_version }}","username":"{{ .Data.data.username }}","password":"{{ .Data.data.password }}"}
{{- end -}}
EOF
}

# Process Supervisor: child starts only after auth + templates succeed.
exec {
  command                   = ["/usr/local/bin/uhbse-synthetic-child"]
  restart_on_secret_changes = "never"
}
