#!/usr/bin/env python3
import os
import subprocess

alias = os.environ.get("TNS_ALIAS", "FREEPDB1_WALLET")
os.environ["TNS_ADMIN"] = os.environ.get("TNS_ADMIN", "/opt/oracle/wallet/network/admin")
sql = "set linesize 200\nselect user as connected_user from dual;\nselect id, message, created_at from wallet_login_demo;\nexit\n"
proc = subprocess.run(
    ["sqlplus", "-L", "-S", "/@{}".format(alias)],
    input=sql,
    universal_newlines=True,
)
raise SystemExit(proc.returncode)
