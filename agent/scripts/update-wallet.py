#!/usr/bin/env python3
import json
import os
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SOCKET_PATH = Path(os.environ.get("WALLETD_SOCKET", "/run/wallet-control/walletd.sock"))
TNS_ALIAS = os.environ.get("TNS_ALIAS", "FREEPDB1_WALLET")
SOCKET_WAIT_SECONDS = int(os.environ.get("SOCKET_WAIT_SECONDS", "60"))


def ts():
    return datetime.now(timezone.utc).strftime("%H:%M:%SZ")


def log(msg):
    print(f"{ts()} [vault-agent] {msg}", flush=True)


def load_payload(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    payload["action"] = payload.get("action") or "update_wallet"
    payload["alias"] = payload.get("alias") or TNS_ALIAS
    username = payload.get("username")
    password = payload.get("password")
    marker = payload.get("rotation_marker") or "unknown"
    if not username or not password:
        raise ValueError(f"rendered payload {path} does not contain username/password")
    return payload, marker, username


def wait_for_socket():
    deadline = time.time() + SOCKET_WAIT_SECONDS
    while time.time() < deadline:
        if SOCKET_PATH.exists():
            return
        log(f"waiting for oracle-wallet-app socket path={SOCKET_PATH}")
        time.sleep(1)
    raise TimeoutError(f"walletd socket not available after {SOCKET_WAIT_SECONDS}s: {SOCKET_PATH}")


def call_walletd(payload):
    raw = (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(30)
        sock.connect(str(SOCKET_PATH))
        sock.sendall(raw)
        response_raw = b""
        while not response_raw.endswith(b"\n"):
            chunk = sock.recv(65536)
            if not chunk:
                break
            response_raw += chunk
    finally:
        sock.close()
    if not response_raw:
        raise RuntimeError("oracle-wallet-app returned empty response")
    response = json.loads(response_raw.decode("utf-8"))
    if response.get("status") != "ok":
        raise RuntimeError(response.get("message") or f"oracle-wallet-app error response: {response}")
    return response


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: update-wallet.py /run/vault-rendered/static-creds.json")
    rendered_path = sys.argv[1]
    payload, marker, username = load_payload(rendered_path)
    log(f"Vault Agent template rendered DBSE credential marker={marker}; sending update_wallet to oracle-wallet-app username={username}")
    wait_for_socket()
    response = call_walletd(payload)
    log(f"oracle-wallet-app acknowledged wallet update marker={marker} oracle_user={response.get('oracle_user')}")
    log("rotation handled end-to-end: Vault DBSE -> Vault Agent template -> update-wallet.py -> app socket -> Oracle wallet -> sqlplus")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log(f"wallet update command failed: {exc}")
        raise
