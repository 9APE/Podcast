"""
auto_refresh_cookies.py

Extracts Google cookies from Chrome and pushes them directly to the
GOOGLE_COOKIES GitHub secret. No manual copy-paste needed.

One-time setup:
  1. Create a GitHub PAT at github.com/settings/tokens/new
     - Name: "Podcast Cookie Refresh"
     - Expiration: No expiration
     - Scope: check "repo" (or just "secrets:write" under repo)
  2. Run: python setup_auto_refresh.ps1  (sets up Windows Task Scheduler)
     It will prompt you for the PAT once and store it locally.

After that, cookies refresh every 10 days automatically.
"""

import json
import os
import sys
import base64
from pathlib import Path

GITHUB_OWNER = "9APE"
GITHUB_REPO  = "Podcast"
SECRET_NAME  = "GOOGLE_COOKIES"
PAT_FILE     = Path(__file__).parent / ".github_pat"

IMPORTANT_COOKIES = {
    "__Secure-1PSID", "__Secure-3PSID",
    "__Secure-1PAPISID", "__Secure-3PAPISID",
    "__Secure-1PSIDTS", "__Secure-3PSIDTS",
    "__Secure-1PSIDCC", "__Secure-3PSIDCC",
    "SID", "HSID", "SSID", "APISID", "SAPISID", "NID",
}


def _ensure(package, import_name=None):
    import importlib
    import_name = import_name or package
    try:
        return importlib.import_module(import_name)
    except ImportError:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", package, "--quiet"])
        return importlib.import_module(import_name)


def get_pat():
    pat = os.environ.get("GITHUB_PAT", "").strip()
    if pat:
        return pat
    if PAT_FILE.exists():
        return PAT_FILE.read_text(encoding="utf-8-sig").strip()
    raise EnvironmentError(
        "GitHub PAT not found.\n"
        "Run setup_auto_refresh.ps1 first, or set the GITHUB_PAT environment variable."
    )


def extract_cookies():
    bc = _ensure("browser_cookie3")
    try:
        cj = bc.chrome(domain_name=".google.com")
        source = "Chrome"
    except Exception as e:
        print(f"  Chrome unavailable ({e}), trying Firefox...")
        cj = bc.firefox(domain_name=".google.com")
        source = "Firefox"

    cookies = []
    for c in cj:
        if c.name in IMPORTANT_COOKIES:
            cookies.append({
                "name": c.name,
                "value": c.value,
                "domain": c.domain if c.domain.startswith(".") else f".{c.domain}",
                "path": c.path or "/",
                "secure": bool(c.secure),
                "httpOnly": False,
                "sameSite": "None",
            })

    print(f"  Extracted {len(cookies)} cookies from {source}.")
    return cookies


def push_to_github(cookies, pat):
    requests = _ensure("requests")
    nacl_public = _ensure("PyNaCl", "nacl.public")
    nacl_encoding = _ensure("PyNaCl", "nacl.encoding")

    from nacl import encoding, public

    headers = {
        "Authorization": f"token {pat}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # 1. Get repo public key
    import requests as req
    r = req.get(
        f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/secrets/public-key",
        headers=headers, timeout=15
    )
    r.raise_for_status()
    key_data = r.json()

    # 2. Encrypt with libsodium
    pub_key = public.PublicKey(key_data["key"].encode("utf-8"), encoding.Base64Encoder())
    box = public.SealedBox(pub_key)
    encrypted = box.encrypt(json.dumps(cookies).encode("utf-8"))
    encrypted_b64 = base64.b64encode(encrypted).decode("utf-8")

    # 3. Update secret
    r = req.put(
        f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/actions/secrets/{SECRET_NAME}",
        headers=headers,
        json={"encrypted_value": encrypted_b64, "key_id": key_data["key_id"]},
        timeout=15
    )
    r.raise_for_status()
    print(f"  GitHub secret '{SECRET_NAME}' updated.")


def main():
    print("=== Auto-refresh Google cookies ===")
    try:
        pat = get_pat()
        cookies = extract_cookies()
        if not cookies:
            print("ERROR: No cookies found — make sure you're logged into Google in your browser.")
            sys.exit(1)
        push_to_github(cookies, pat)
        print("Done. Cookies are fresh.")
    except Exception as e:
        print(f"FAILED: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
