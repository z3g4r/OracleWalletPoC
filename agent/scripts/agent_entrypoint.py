#!/usr/bin/env python3
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

TOKEN_DIR = Path("/vault/token")
INPUT_TOKEN = TOKEN_DIR / "input-token"
CONFIG_PATH = "/vault/project/config/agent.hcl"
RENDER_DIR = Path("/run/vault-rendered")


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


def terminate(proc):
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def main():
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    RENDER_DIR.mkdir(parents=True, exist_ok=True)
    INPUT_TOKEN.write_text(os.environ.get("VAULT_TOKEN", "root"), encoding="utf-8")
    try:
        INPUT_TOKEN.chmod(0o640)
    except PermissionError:
        pass

    wait_for_vault()
    log("starting official Vault Agent: auth + token sink + template watcher")
    log("Vault Agent template watches database/static-creds/app-user-wallet and runs update-wallet.py on render changes")
    agent_proc = subprocess.Popen(["vault", "agent", "-config", CONFIG_PATH], env=os.environ.copy())

    def handle_signal(signum, frame):
        log(f"received signal {signum}; stopping Vault Agent")
        terminate(agent_proc)
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    while True:
        if agent_proc.poll() is not None:
            log(f"Vault Agent exited with code {agent_proc.returncode}")
            return agent_proc.returncode
        time.sleep(1)


if __name__ == "__main__":
    sys.exit(main())
