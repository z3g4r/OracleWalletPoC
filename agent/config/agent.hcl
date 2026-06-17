vault {
  address = "http://vault:8200"
}

auto_auth {
  method "token_file" {
    config = {
      token_file_path = "/vault/token/input-token"
    }
  }

  sink "file" {
    config = {
      path = "/vault/token/agent-token"
      mode = 0640
    }
  }
}

template_config {
  # Keep the PoC responsive. Static DBSE credentials with rotation_period are
  # refreshed by Vault Agent based on secret timing; this also keeps generic
  # static-secret rendering short if Vault treats a response as non-leased.
  static_secret_render_interval = "5s"
}

template {
  destination = "/run/vault-rendered/static-creds.json"
  perms       = "0600"
  command     = "python3 /vault/project/scripts/update-wallet.py /run/vault-rendered/static-creds.json"
  command_timeout = "60s"

  contents = <<EOH
{{- with secret "database/static-creds/app-user-wallet" -}}
{
  "action": "update_wallet",
  "username": "{{ .Data.username }}",
  "password": "{{ .Data.password }}",
  "rotation_marker": "last_vault_rotation:{{ .Data.last_vault_rotation }}"
}
{{- end -}}
EOH
}
