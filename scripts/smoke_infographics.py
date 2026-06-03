#!/usr/bin/env python3
"""Smoke test the @vercel/og infographic endpoints.

Guards against the Satori "0-byte" regression: when an infographic route hits a
Satori error (e.g. a multi-child or bare-numeric JSX child) it catches the throw
and returns HTTP 200 with an EMPTY body. Every external check looks healthy, but
Postiz rejects the 0-byte upload days later. This fails fast if any endpoint
returns a 200 image with a suspiciously small body.

Run locally or in CI against any base URL:

    python scripts/smoke_infographics.py --base-url https://pitchrank.io
"""

import argparse
import sys

import requests

# Windows' Python ships a certifi bundle that can miss intermediates for some hosts;
# use the OS trust store when available so local runs verify TLS. No-op on CI (Linux
# verifies natively) and harmless if truststore isn't installed.
try:
    import truststore

    truststore.inject_into_ssl()
except Exception:  # noqa: BLE001
    pass

# (path, allow_404) — spotlight legitimately 404s when there is no mover data that
# week, which is not a render bug; everything else must return a real image.
ENDPOINTS = [
    ("/api/infographic/movers?platform=instagram", False),
    ("/api/infographic/movers?platform=story", False),
    ("/api/infographic/spotlight?platform=instagram", True),
    ("/api/infographic/spotlight?platform=story", True),
    ("/api/infographic/state?state=TX&age=u14&gender=male&platform=instagram", False),
    ("/api/infographic/state?state=CA&age=u15&gender=male&platform=story", False),
]

# A real infographic PNG is >100 KB; the 0-byte Satori failure returns 0 bytes.
MIN_BYTES = 5000


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="https://pitchrank.io")
    parser.add_argument("--min-bytes", type=int, default=MIN_BYTES)
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    failures: list[str] = []

    for path, allow_404 in ENDPOINTS:
        url = base + path
        try:
            resp = requests.get(url, timeout=60)
        except Exception as e:  # noqa: BLE001 — any failure is a smoke-test failure
            failures.append(f"{path} -> request error: {e}")
            continue

        size = len(resp.content)
        ctype = resp.headers.get("content-type", "")

        if resp.status_code == 404 and allow_404:
            print(f"OK   (no data, 404)        {path}")
            continue
        if resp.status_code != 200:
            failures.append(f"{path} -> HTTP {resp.status_code}")
            continue
        if "image" not in ctype:
            failures.append(f"{path} -> 200 but content-type '{ctype}' (expected an image)")
            continue
        if size < args.min_bytes:
            failures.append(
                f"{path} -> 200 image but only {size} bytes (< {args.min_bytes}; 0-byte Satori regression?)"
            )
            continue

        print(f"OK   {size:>8,} bytes       {path}")

    if failures:
        print("\nFAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("\nAll infographic endpoints rendered real images.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
