#!/usr/bin/env python3
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SOCKET_PATH = Path(os.environ.get("WALLETD_SOCKET", "/run/wallet-control/walletd.sock"))
WALLET_ROOT = Path("/opt/oracle/wallet")
WALLET_DIR = WALLET_ROOT / "password-store"
NETWORK_DIR = WALLET_ROOT / "network" / "admin"
TNS_ALIAS = os.environ.get("TNS_ALIAS", "FREEPDB1_WALLET")
DB_HOST = os.environ.get("DB_HOST", "oracle-db")
DB_PORT = os.environ.get("DB_PORT", "1521")
DB_SERVICE = os.environ.get("DB_SERVICE", "FREEPDB1")
WALLET_PASSWORD = os.environ.get("WALLET_PASSWORD", "WalletPassword1")


def ts():
    return datetime.now(timezone.utc).strftime("%H:%M:%SZ")


def log(msg):
    print(f"{ts()} [oracle-wallet-app] {msg}", flush=True)


def run(cmd, input_text=None, env=None):
    return subprocess.run(
        cmd,
        universal_newlines=True,
        input=input_text,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def write_net_config():
    NETWORK_DIR.mkdir(parents=True, exist_ok=True)
    (NETWORK_DIR / "sqlnet.ora").write_text(f"""WALLET_LOCATION =
  (SOURCE =
    (METHOD = FILE)
    (METHOD_DATA =
      (DIRECTORY = {WALLET_DIR})
    )
  )

SQLNET.WALLET_OVERRIDE = TRUE
""", encoding="utf-8")
    (NETWORK_DIR / "tnsnames.ora").write_text(f"""{TNS_ALIAS} =
  (DESCRIPTION =
    (ADDRESS = (PROTOCOL = TCP)(HOST = {DB_HOST})(PORT = {DB_PORT}))
    (CONNECT_DATA =
      (SERVICE_NAME = {DB_SERVICE})
    )
  )
""", encoding="utf-8")
    log(f"Oracle Net config ready alias={TNS_ALIAS} target={DB_HOST}:{DB_PORT}/{DB_SERVICE}")


def mkstore(args, input_text=None, check=True):
    proc = run(["mkstore"] + args, input_text=input_text)
    if check and proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "mkstore failed").strip())
    return proc


def create_wallet_if_needed():
    WALLET_DIR.mkdir(parents=True, exist_ok=True)
    if not (WALLET_DIR / "ewallet.p12").exists():
        log(f"creating Oracle Secure External Password Store wallet dir={WALLET_DIR}")
        mkstore(["-wrl", str(WALLET_DIR), "-create"], input_text=f"{WALLET_PASSWORD}\n{WALLET_PASSWORD}\n")


def update_wallet(username, password, marker):
    create_wallet_if_needed()
    log(f"updating wallet alias={TNS_ALIAS} username={username} marker={marker}")
    mkstore(["-wrl", str(WALLET_DIR), "-deleteCredential", TNS_ALIAS], input_text=f"{WALLET_PASSWORD}\n", check=False)
    mkstore(["-wrl", str(WALLET_DIR), "-createCredential", TNS_ALIAS, username, password], input_text=f"{WALLET_PASSWORD}\n")
    write_net_config()


def login_test():
    env = os.environ.copy()
    env["TNS_ADMIN"] = str(NETWORK_DIR)
    sql = "set heading off feedback off pagesize 0\nselect user from dual;\nexit\n"
    proc = run(["sqlplus", "-L", "-S", f"/@{TNS_ALIAS}"], input_text=sql, env=env)
    output = (proc.stdout + proc.stderr).strip()
    WALLET_DIR.mkdir(parents=True, exist_ok=True)
    (WALLET_DIR / "last-login-test.txt").write_text(output + "\n", encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(output)
    oracle_user = output.replace("\n", " | ")
    log(f"wallet login test ok user={oracle_user}")
    return oracle_user


def handle_request(payload):
    action = payload.get("action")
    if action != "update_wallet":
        raise ValueError(f"unsupported action: {action}")
    username = payload.get("username")
    password = payload.get("password")
    marker = payload.get("rotation_marker") or "unknown"
    alias = payload.get("alias") or TNS_ALIAS
    if alias != TNS_ALIAS:
        raise ValueError(f"unexpected alias: {alias}; expected {TNS_ALIAS}")
    if not username or not password:
        raise ValueError("username/password are required")
    log(f"update request received username={username} marker={marker}")
    update_wallet(username, password, marker)
    oracle_user = login_test()
    return {"status": "ok", "oracle_user": oracle_user, "rotation_marker": marker}


def serve():
    for p in (WALLET_DIR, NETWORK_DIR, SOCKET_PATH.parent):
        p.mkdir(parents=True, exist_ok=True)
    if SOCKET_PATH.exists():
        SOCKET_PATH.unlink()
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(SOCKET_PATH))
    os.chmod(str(SOCKET_PATH), 0o666)
    sock.listen(5)
    log(f"walletd listening socket={SOCKET_PATH}; waiting for vault-agent update_wallet requests")
    try:
        while True:
            conn, _ = sock.accept()
            with conn:
                raw = b""
                while not raw.endswith(b"\n"):
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    raw += chunk
                try:
                    payload = json.loads(raw.decode("utf-8"))
                    response = handle_request(payload)
                except Exception as exc:
                    log(f"wallet update request failed: {exc}")
                    response = {"status": "error", "message": str(exc)}
                conn.sendall((json.dumps(response, sort_keys=True) + "\n").encode("utf-8"))
    finally:
        sock.close()
        try:
            SOCKET_PATH.unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    sys.exit(serve())
