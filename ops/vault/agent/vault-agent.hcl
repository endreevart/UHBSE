# Vault Agent — UHBSE runtime-auth v0.1
# Secrets live only under tmpfs /run/uhbse-vault (never repository storage).
# role_id and wrapped SecretID are delivered separately by the operator script.

pid_file = "/run/uhbse-vault/agent.pid"
exit_after_auth = false

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

template {
  destination = "/run/uhbse-vault/secrets/hmac-subject-key.json"
  perms       = "0600"
  contents    = <<EOF
{{- with secret "uhbse/data/canonical/hmac-subject-key" -}}
{"key_version":"{{ .Data.data.key_version }}","algorithm":"{{ .Data.data.algorithm }}","key_material":"{{ .Data.data.key_material }}"}
{{- end -}}
EOF
}

template {
  destination = "/run/uhbse-vault/secrets/loader-credential.json"
  perms       = "0600"
  contents    = <<EOF
{{- with secret "uhbse/data/canonical/loader-credential" -}}
{"key_version":"{{ .Data.data.key_version }}","username":"{{ .Data.data.username }}","password":"{{ .Data.data.password }}"}
{{- end -}}
EOF
}
