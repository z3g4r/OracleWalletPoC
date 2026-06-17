#!/usr/bin/env python3
import base64
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from urllib import request, error

WALLET_APP_URL = os.environ.get("WALLET_APP_URL", "http://oracle-wallet-app:8080/wallet/update")
JWT_PRIVATE_KEY_PATH = os.environ.get("JWT_PRIVATE_KEY_PATH", "/run/wallet-jwt/private.pem")
JWT_ISSUER = os.environ.get("JWT_ISSUER", "vault-agent")
JWT_AUDIENCE = os.environ.get("JWT_AUDIENCE", "oracle-wallet-app")
JWT_TTL_SECONDS = int(os.environ.get("JWT_TTL_SECONDS", "60"))
TNS_ALIAS = os.environ.get("TNS_ALIAS", "FREEPDB1_WALLET")

running = True


def ts():
    return datetime.now(timezone.utc).strftime("%H:%M:%SZ")


def log(msg):
    print(f"{ts()} [vault-agent] {msg}", flush=True)


def handle_signal(signum, frame):
    global running
    log(f"process supervisor stop signal received signum={signum}; exiting child")
    running = False


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def json_b64url(obj):
    raw = json.dumps(obj, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return b64url(raw)


def openssl_sign_rs256(data):
    proc = subprocess.run(
        ["openssl", "dgst", "-sha256", "-sign", JWT_PRIVATE_KEY_PATH],
        input=data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or b"openssl signing failed").decode("utf-8", "replace").strip())
    return proc.stdout


def build_jwt(rotation_marker):
    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    claims = {
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "sub": "wallet-update",
        "iat": now,
        "nbf": now,
        "exp": now + JWT_TTL_SECONDS,
        "jti": str(uuid.uuid4()),
        "rotation_marker": rotation_marker,
    }
    signing_input = f"{json_b64url(header)}.{json_b64url(claims)}".encode("ascii")
    signature = openssl_sign_rs256(signing_input)
    return signing_input.decode("ascii") + "." + b64url(signature)


def get_env_payload():
    username = os.environ.get("DB_USERNAME")
    password = os.environ.get("DB_PASSWORD")
    marker = os.environ.get("ROTATION_MARKER") or "unknown"
    missing = [name for name, value in (("DB_USERNAME", username), ("DB_PASSWORD", password)) if not value]
    if missing:
        raise RuntimeError(f"missing required env vars from Vault Agent: {', '.join(missing)}")
    return {
        "action": "update_wallet",
        "alias": TNS_ALIAS,
        "username": username,
        "password": password,
        "rotation_marker": marker,
    }


def send_to_wallet_app(payload):
    marker = payload.get("rotation_marker", "unknown")
    token = build_jwt(marker)
    body = json.dumps(payload, sort_keys=True).encode("utf-8")
    req = request.Request(
        WALLET_APP_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            status = resp.status
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"oracle-wallet-app HTTP {exc.code}: {raw}")
    if status < 200 or status >= 300:
        raise RuntimeError(f"oracle-wallet-app HTTP {status}: {raw}")
    response = json.loads(raw)
    if response.get("status") != "ok":
        raise RuntimeError(response.get("message") or f"wallet app error response: {response}")
    return response


def update_until_success(payload):
    marker = payload.get("rotation_marker")
    username = payload.get("username")
    while running:
        try:
            log(f"Vault Agent process supervisor triggered wallet update marker={marker} username={username}")
            log(f"signing wallet update JWT issuer={JWT_ISSUER} audience={JWT_AUDIENCE} marker={marker}")
            log(f"sending HTTP update_wallet request url={WALLET_APP_URL}")
            response = send_to_wallet_app(payload)
            log(f"oracle-wallet-app acknowledged wallet update marker={marker} oracle_user={response.get('oracle_user')}")
            log("rotation handled end-to-end: Vault DBSE -> Vault Agent env_template/process-supervisor -> signed HTTP -> Oracle wallet -> sqlplus")
            return
        except Exception as exc:
            log(f"wallet update failed; retrying: {exc}")
            time.sleep(2)


def main():
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)
    payload = get_env_payload()
    update_until_success(payload)
    log("update-wallet.py child is idle; waiting for Vault Agent to restart it on the next secret change")
    while running:
        time.sleep(3600)
    return 0


if __name__ == "__main__":
    sys.exit(main())
