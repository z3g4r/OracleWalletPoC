#!/usr/bin/env python3
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

WALLET_ROOT = Path("/opt/oracle/wallet")
WALLET_DIR = WALLET_ROOT / "password-store"
NETWORK_DIR = WALLET_ROOT / "network" / "admin"
TNS_ALIAS = os.environ.get("TNS_ALIAS", "FREEPDB1_WALLET")
DB_HOST = os.environ.get("DB_HOST", "oracle-db")
DB_PORT = os.environ.get("DB_PORT", "1521")
DB_SERVICE = os.environ.get("DB_SERVICE", "FREEPDB1")
WALLET_PASSWORD = os.environ.get("WALLET_PASSWORD", "WalletPassword1")
HTTP_HOST = os.environ.get("WALLET_HTTP_HOST", "0.0.0.0")
HTTP_PORT = int(os.environ.get("WALLET_HTTP_PORT", "8080"))
JWT_PUBLIC_KEY_PATH = os.environ.get("JWT_PUBLIC_KEY_PATH", "/run/wallet-jwt/public.pem")
JWT_ISSUER = os.environ.get("JWT_ISSUER", "vault-agent")
JWT_AUDIENCE = os.environ.get("JWT_AUDIENCE", "oracle-wallet-app")
JWT_CLOCK_SKEW_SECONDS = int(os.environ.get("JWT_CLOCK_SKEW_SECONDS", "5"))


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


def b64url_decode(text):
    return base64.urlsafe_b64decode((text + "=" * (-len(text) % 4)).encode("ascii"))


def verify_rs256(signing_input, signature):
    with tempfile.NamedTemporaryFile(prefix="wallet-jwt-sig-", delete=True) as sig_file, \
            tempfile.NamedTemporaryFile(prefix="wallet-jwt-input-", delete=True) as input_file:
        sig_file.write(signature)
        sig_file.flush()
        input_file.write(signing_input)
        input_file.flush()
        proc = subprocess.run(
            ["openssl", "dgst", "-sha256", "-verify", JWT_PUBLIC_KEY_PATH, "-signature", sig_file.name, input_file.name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    if proc.returncode != 0:
        raise PermissionError("JWT signature verification failed")


def verify_jwt(token):
    try:
        header_b64, claims_b64, sig_b64 = token.split(".")
    except ValueError:
        raise PermissionError("invalid JWT format")
    signing_input = f"{header_b64}.{claims_b64}".encode("ascii")
    header = json.loads(b64url_decode(header_b64).decode("utf-8"))
    claims = json.loads(b64url_decode(claims_b64).decode("utf-8"))
    signature = b64url_decode(sig_b64)
    if header.get("alg") != "RS256" or header.get("typ") != "JWT":
        raise PermissionError("unsupported JWT header")
    verify_rs256(signing_input, signature)

    now = int(time.time())
    if claims.get("iss") != JWT_ISSUER:
        raise PermissionError("invalid JWT issuer")
    aud = claims.get("aud")
    if aud != JWT_AUDIENCE and not (isinstance(aud, list) and JWT_AUDIENCE in aud):
        raise PermissionError("invalid JWT audience")
    if claims.get("sub") != "wallet-update":
        raise PermissionError("invalid JWT subject")
    if int(claims.get("nbf", 0)) > now + JWT_CLOCK_SKEW_SECONDS:
        raise PermissionError("JWT not yet valid")
    if int(claims.get("exp", 0)) < now - JWT_CLOCK_SKEW_SECONDS:
        raise PermissionError("JWT expired")
    if "jti" not in claims:
        raise PermissionError("JWT missing jti")
    return claims


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


def handle_request(payload, claims):
    action = payload.get("action")
    if action != "update_wallet":
        raise ValueError(f"unsupported action: {action}")
    username = payload.get("username")
    password = payload.get("password")
    marker = payload.get("rotation_marker") or "unknown"
    alias = payload.get("alias") or TNS_ALIAS
    if claims.get("rotation_marker") != marker:
        raise PermissionError("JWT rotation_marker does not match request body")
    if alias != TNS_ALIAS:
        raise ValueError(f"unexpected alias: {alias}; expected {TNS_ALIAS}")
    if not username or not password:
        raise ValueError("username/password are required")
    log(f"verified wallet update JWT issuer={claims.get('iss')} subject={claims.get('sub')} marker={marker}")
    log(f"update request received username={username} marker={marker}")
    update_wallet(username, password, marker)
    oracle_user = login_test()
    return {"status": "ok", "oracle_user": oracle_user, "rotation_marker": marker}


class WalletRequestHandler(BaseHTTPRequestHandler):
    server_version = "walletd-http/1.0"

    def log_message(self, fmt, *args):
        log("http " + fmt % args)

    def write_json(self, status, payload):
        raw = (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/healthz":
            self.write_json(200, {"status": "ok"})
        else:
            self.write_json(404, {"status": "error", "message": "not found"})

    def do_POST(self):
        if self.path != "/wallet/update":
            self.write_json(404, {"status": "error", "message": "not found"})
            return
        try:
            auth = self.headers.get("Authorization", "")
            if not auth.startswith("Bearer "):
                raise PermissionError("missing Bearer token")
            token = auth[len("Bearer "):].strip()
            claims = verify_jwt(token) ### TOKEN VERIFICATION
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1024 * 1024:
                raise ValueError("invalid request body length")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            response = handle_request(payload, claims) ### PROCESSING START
            self.write_json(200, response)
        except PermissionError as exc:
            log(f"wallet update request rejected: {exc}")
            self.write_json(401, {"status": "error", "message": str(exc)})
        except Exception as exc:
            log(f"wallet update request failed: {exc}")
            self.write_json(500, {"status": "error", "message": str(exc)})


def serve():
    for p in (WALLET_DIR, NETWORK_DIR):
        p.mkdir(parents=True, exist_ok=True)
    server = HTTPServer((HTTP_HOST, HTTP_PORT), WalletRequestHandler)
    log(f"wallet HTTP server listening address={HTTP_HOST}:{HTTP_PORT}; waiting for signed vault-agent update_wallet requests")
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    sys.exit(serve())
