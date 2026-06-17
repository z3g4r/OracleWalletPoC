#!/usr/bin/env python3
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

VAULT_ADDR = os.environ.get("VAULT_ADDR", "http://127.0.0.1:8200")
VAULT_TOKEN = os.environ.get("VAULT_TOKEN", "root")
PLUGIN_PATH = Path("/vault/plugins/vault-plugin-database-oracle")
APP_USER = os.environ.get("APP_USER", "app_user")
APP_INITIAL_PASSWORD = os.environ.get("APP_INITIAL_PASSWORD", "AppPassword1")
ORACLE_PASSWORD = os.environ.get("ORACLE_PASSWORD", "OraclePassword1")
DB_HOST = os.environ.get("DB_HOST", "oracle-db")
DB_PORT = os.environ.get("DB_PORT", "1521")
DB_SERVICE = os.environ.get("DB_SERVICE", "FREEPDB1")
ROTATION_PERIOD = os.environ.get("ROTATION_PERIOD", "30s")


def ts():
    return datetime.now(timezone.utc).strftime("%H:%M:%SZ")


def log(msg):
    print(f"{ts()} [vault] {msg}", flush=True)


def run(cmd, check=True, input_text=None, env_extra=None):
    env = os.environ.copy()
    env["VAULT_ADDR"] = VAULT_ADDR
    env["VAULT_TOKEN"] = VAULT_TOKEN
    if env_extra:
        env.update(env_extra)
    redacted = []
    for part in cmd:
        redacted.append("***" if any(secret and secret in part for secret in [ORACLE_PASSWORD, APP_INITIAL_PASSWORD]) else part)
    log("running: " + " ".join(redacted))
    proc = subprocess.run(
        cmd,
        check=False,
        universal_newlines=True,
        input=input_text,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        if proc.stdout.strip():
            log("stdout: " + proc.stdout.strip())
        if proc.stderr.strip():
            log("stderr: " + proc.stderr.strip())
        if check:
            raise subprocess.CalledProcessError(proc.returncode, proc.args, output=proc.stdout, stderr=proc.stderr)
    return proc


def wait_for_vault():
    for _ in range(120):
        proc = run(["vault", "status", "-format=json"], check=False)
        if proc.returncode in (0, 2):
            return
        time.sleep(1)
    raise RuntimeError("Vault did not become reachable")


def maybe_run(cmd):
    proc = run(cmd, check=False)
    if proc.returncode != 0:
        log((proc.stderr or proc.stdout).strip())
    return proc


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def configure_database_engine():
    if not PLUGIN_PATH.exists():
        raise RuntimeError(f"Oracle database plugin missing at {PLUGIN_PATH}")

    maybe_run(["vault", "secrets", "enable", "database"])

    plugin_sha = sha256_file(PLUGIN_PATH)
    run([
        "vault", "write", "sys/plugins/catalog/database/vault-plugin-database-oracle",
        f"sha256={plugin_sha}",
        "command=vault-plugin-database-oracle",
    ])

    connection_url = "{{username}}/{{password}}@//" + f"{DB_HOST}:{DB_PORT}/{DB_SERVICE}"
    run([
        "vault", "write", "database/config/oracle-free",
        "plugin_name=vault-plugin-database-oracle",
        "allowed_roles=app-user-wallet",
        f"connection_url={connection_url}",
        "username=system",
        f"password={ORACLE_PASSWORD}",
    ])

    rotation_sql = 'ALTER USER {{username}} IDENTIFIED BY "{{password}}" ACCOUNT UNLOCK'
    run([
        "vault", "write", "database/static-roles/app-user-wallet",
        "db_name=oracle-free",
        f"username={APP_USER}",
        f"rotation_period={ROTATION_PERIOD}",
        f"rotation_statements={rotation_sql}",
    ])

    # Force an initial rotation so Vault, Oracle, and the static-creds endpoint agree immediately.
    maybe_run(["vault", "write", "-force", "database/rotate-role/app-user-wallet"])
    log(f"DBSE static role configured role=app-user-wallet user={APP_USER} rotation_period={ROTATION_PERIOD}")


def main():
    # External database plugins must be inside Vault's configured plugin directory.
    # VAULT_PLUGIN_DIR is not enough for `vault server -dev`; pass -dev-plugin-dir
    # so plugin catalog registration can validate /vault/plugins/vault-plugin-database-oracle.
    vault_proc = subprocess.Popen([
        "vault", "server", "-dev", "-dev-root-token-id", VAULT_TOKEN,
        "-dev-listen-address", "0.0.0.0:8200",
        "-dev-plugin-dir", "/vault/plugins",
    ], env={**os.environ, "VAULT_ADDR": VAULT_ADDR, "VAULT_TOKEN": VAULT_TOKEN})
    try:
        wait_for_vault()
        configure_database_engine()
        log("Vault ready: Database Secrets Engine owns app_user password rotation")
        return vault_proc.wait()
    finally:
        if vault_proc.poll() is None:
            vault_proc.terminate()


if __name__ == "__main__":
    sys.exit(main())
