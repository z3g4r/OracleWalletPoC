#!/usr/bin/env bash
set -euo pipefail
mkdir -p jwt-keys
openssl genrsa -out jwt-keys/agent-private.pem 2048
openssl rsa -in jwt-keys/agent-private.pem -pubout -out jwt-keys/agent-public.pem
chmod 0644 jwt-keys/agent-private.pem jwt-keys/agent-public.pem
cat <<MSG
Generated demo JWT key pair:
  jwt-keys/agent-private.pem
  jwt-keys/agent-public.pem

For production, do not commit or bake the private key into an image or repo artifact.
Inject it into vault-agent from your platform secret manager.
MSG
