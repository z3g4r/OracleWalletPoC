vault {
  address = "http://vault:8200"
}

template_config {
  #re-check static secrets often so 30s DBSE rotation is visible quickly.
  static_secret_render_interval = "5s"
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

env_template "DB_USERNAME" {
  contents = "{{ with secret \"database/static-creds/app-user-wallet\" }}{{ .Data.username }}{{ end }}"
  error_on_missing_key = true
}

env_template "DB_PASSWORD" {
  contents = "{{ with secret \"database/static-creds/app-user-wallet\" }}{{ .Data.password }}{{ end }}"
  error_on_missing_key = true
}

env_template "ROTATION_MARKER" {
  contents = "{{ with secret \"database/static-creds/app-user-wallet\" }}last_vault_rotation:{{ .Data.last_vault_rotation }}{{ end }}"
  error_on_missing_key = true
}

exec {
  command = ["python3", "/vault/project/scripts/update-wallet.py"]
  restart_on_secret_changes = "always"
  restart_stop_signal = "SIGTERM"
}
