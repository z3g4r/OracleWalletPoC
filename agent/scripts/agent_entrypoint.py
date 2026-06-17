#!/usr/bin/env python3
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

TOKEN_DIR = Path("/vault/token")
INPUT_TOKEN = TOKEN_DIR / "input-token"
CONFIG_PATH = "/vault/project/config/agent.hcl"


def ts():
    return datetime.now(timezone.utc).strftime("%H:%M:%SZ")


def log(msg):
    print(f"{ts()} [vault-agent] {msg}", flush=True)


def wait_for_vault():
    while True:
        proc = subprocess.run(["vault", "status"], env=os.environ.copy(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if proc.returncode in (0, 2):
            log("Vault API reachable")
            return
        log("waiting for Vault API")
        time.sleep(1)


def main():
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    INPUT_TOKEN.write_text(os.environ.get("VAULT_TOKEN", "root"), encoding="utf-8")
    try:
        INPUT_TOKEN.chmod(0o640)
    except PermissionError:
        pass

    wait_for_vault()
    log("starting official Vault Agent in process-supervisor mode")
    log("Vault Agent env_template watches database/static-creds/app-user-wallet")
    log("on secret change Vault Agent restarts update-wallet.py with DB_USERNAME/DB_PASSWORD/ROTATION_MARKER env vars")
    os.execvp("vault", ["vault", "agent", "-config", CONFIG_PATH])


if __name__ == "__main__":
    sys.exit(main())
