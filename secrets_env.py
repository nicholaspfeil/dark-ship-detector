"""
secrets_env.py — read secrets (API keys, tokens, phone numbers) without hardcoding them.

Looks in the normal environment first, then (on Windows) in the variables
saved for your user account with [Environment]::SetEnvironmentVariable(...,"User").
Saved user variables only reach new terminals, so this second lookup means
you don't have to reopen PowerShell after saving one.
"""

import os
import subprocess


def get_secret(name, required=True):
    value = os.environ.get(name)
    if not value and os.name == "nt":
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f'[Environment]::GetEnvironmentVariable("{name}","User")'],
            capture_output=True, text=True)
        value = out.stdout.strip()
    if not value and required:
        raise SystemExit(f"{name} is not set.")
    return value or None
