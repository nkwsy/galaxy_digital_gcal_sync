"""Smoke-test Galaxy Digital API credentials in .env.

Run: `python verify_galaxy_creds.py`. Exits 0 on success, 1 on failure.
Prints which endpoints work and surfaces one sample record per endpoint
so the field shapes can be confirmed against api.yaml.
"""
import os
import sys
import json
import requests
from dotenv import load_dotenv


def main() -> int:
    load_dotenv()
    api_key = (os.getenv("API_KEY") or "").strip()
    email = (os.getenv("EMAIL") or "").strip()
    password = (os.getenv("PASSWORD") or "").strip()

    missing = [n for n, v in [("API_KEY", api_key), ("EMAIL", email), ("PASSWORD", password)] if not v]
    if missing:
        print(f"missing env vars: {missing}")
        return 1

    base = "https://api.galaxydigital.com/api"
    print(f"login: POST {base}/users/login as {email!r}")
    r = requests.post(
        f"{base}/users/login",
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        json={"key": api_key, "user_email": email, "user_password": password},
        timeout=15,
    )
    if r.status_code != 200:
        print(f"  -> HTTP {r.status_code}: {r.text[:300]}")
        print("  fix: update API_KEY / EMAIL / PASSWORD in .env, then rerun.")
        return 1

    payload = r.json()
    token = payload["data"]["token"] if isinstance(payload.get("data"), dict) else payload["data"][0]["token"]
    print(f"  -> ok, token prefix={token[:12]}...")

    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    for path, params in [
        ("responses", {"per_page": 1}),
        ("hours", {"per_page": 1}),
        ("users", {"per_page": 1}),
        ("needs", {"per_page": 1}),
    ]:
        r = requests.get(f"{base}/{path}", headers=headers, json=params, timeout=15)
        ok = r.status_code == 200
        data = r.json().get("data") if ok else None
        sample = data[0] if data else None
        print(f"GET /{path}: HTTP {r.status_code}  records={len(data) if data else 0}")
        if sample:
            print(f"  sample keys: {sorted(sample.keys())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
