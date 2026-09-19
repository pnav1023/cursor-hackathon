#!/usr/bin/env python3
"""Verify Invoice Ninja credentials from repo .env via GET /api/v1/ping."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[4]


def _load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("'").strip('"')
    return values


def main() -> int:
    env = _load_env(ROOT / ".env")
    token = env.get("INVOICE_NINJA_API_TOKEN", "").strip()
    base = env.get("INVOICE_NINJA_BASE_URL", "https://invoicing.co").strip().rstrip("/")
    secret = env.get("INVOICE_NINJA_API_SECRET", "").strip()
    if not token:
        print("Missing INVOICE_NINJA_API_TOKEN in .env", file=sys.stderr)
        return 2

    url = f"{base}/api/v1/ping"
    headers = {
        "Accept": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "X-API-TOKEN": token,
    }
    if secret:
        headers["X-API-SECRET"] = secret
    request = Request(url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            status = response.status
    except HTTPError as exc:
        print(f"Ping failed HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}", file=sys.stderr)
        return 1
    except URLError as exc:
        print(f"Cannot reach {url}: {exc}", file=sys.stderr)
        return 1

    print(f"ok {status} {url}")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        print(body[:500])
        return 0
    print(json.dumps(payload, indent=2)[:2000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
