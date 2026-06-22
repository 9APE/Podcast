"""
extract_google_cookies.py — run this ONCE on your own computer to get
the Google auth cookies that NotebookLM needs.

Steps:
1. Make sure you're logged into Google in Chrome
2. Run:  python extract_google_cookies.py
3. Copy the JSON output
4. Go to GitHub repo -> Settings -> Secrets -> Actions -> New secret
   Name:  GOOGLE_COOKIES
   Value: [paste the JSON]

Cookies expire roughly every 2 weeks. Re-run when NotebookLM starts
failing with auth errors.
"""

import json
import sys

try:
    import browser_cookie3
except ImportError:
    print("Installing browser_cookie3...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "browser_cookie3"])
    import browser_cookie3

print("Extracting Google cookies from Chrome...")
print("(You may see a keychain/password prompt on Mac — that's normal)\n")

try:
    cj = browser_cookie3.chrome(domain_name=".google.com")
except Exception as e:
    print(f"Chrome failed ({e}), trying Firefox...")
    cj = browser_cookie3.firefox(domain_name=".google.com")

cookies = []
for c in cj:
    cookies.append({
        "name": c.name,
        "value": c.value,
        "domain": c.domain if c.domain.startswith(".") else f".{c.domain}",
        "path": c.path or "/",
        "secure": bool(c.secure),
        "httpOnly": False,
        "sameSite": "None",
    })

# Filter to only the cookies NotebookLM actually needs
important = {
    "__Secure-1PSID", "__Secure-3PSID", "__Secure-1PAPISID", "__Secure-3PAPISID",
    "SID", "HSID", "SSID", "APISID", "SAPISID", "NID", "1P_JAR",
    "__Secure-1PSIDTS", "__Secure-3PSIDTS", "__Secure-1PSIDCC", "__Secure-3PSIDCC",
}
filtered = [c for c in cookies if c["name"] in important]
if not filtered:
    filtered = cookies  # fall back to all if filtering got nothing

output = json.dumps(filtered, indent=2)

print(f"Found {len(filtered)} relevant Google cookies.\n")
print("=" * 60)
print("COPY EVERYTHING BELOW THIS LINE:")
print("=" * 60)
print(output)
print("=" * 60)
print("\nAdd this as GitHub secret named: GOOGLE_COOKIES")
print("Expires in ~2 weeks. Re-run this script when auth fails.")
