"""Dump raw API responses for each get_* endpoint to tests/fixtures/.

Usage:
    WATTS_USER=you@example.com WATTS_PASS=secret \
        python scripts/dump_fixtures.py

Writes (or overwrites):
    tests/fixtures/user_details.json
    tests/fixtures/locations.json
    tests/fixtures/devices.json   (refreshes existing file)

Sensitive values in the output are scrubbed:
    - Top-level token/credential fields are not part of these endpoints,
      so nothing needs scrubbing beyond what the API already omits.
    - Device names and location names are left as-is so fixture tests
      reflect real structure; scrub manually if you prefer.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# Allow running from the repo root without installing the package.
sys.path.insert(0, str(Path(__file__).parent.parent))

from curl_cffi.requests import AsyncSession  # noqa: E402

from custom_components.watts_home.api import WattsApiClient  # noqa: E402
from custom_components.watts_home.auth import WattsAuth  # noqa: E402
from custom_components.watts_home.const import BROWSER_UA  # noqa: E402

FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures"


async def main() -> None:
    username = os.environ.get("WATTS_USER") or input("Watts username: ")
    password = os.environ.get("WATTS_PASS") or input("Watts password: ")

    async with AsyncSession(impersonate="chrome110") as session:
        print("Authenticating…")
        tokens = await WattsAuth.login(session, username, password)

        print("GET /User/Details")
        user_details = await _raw_get(session, tokens["access_token"], "/User/Details")
        _write(FIXTURES / "user_details.json", user_details)

        print("GET /Location")
        locations_raw = await _raw_get(session, tokens["access_token"], "/Location")
        _write(FIXTURES / "locations.json", locations_raw)

        locations: list = locations_raw["body"]
        location = WattsApiClient.find_default_location(locations)
        location_id = str(location["locationId"])
        print(f"GET /Location/{location_id}/Devices")
        devices_raw = await _raw_get(
            session, tokens["access_token"], f"/Location/{location_id}/Devices"
        )
        _write(FIXTURES / "devices.json", devices_raw)

    print("\nDone. Fixtures written to tests/fixtures/")


async def _raw_get(session: AsyncSession, token: str, path: str) -> dict:
    from custom_components.watts_home.const import API_BASE_URL

    headers = {
        "Api-Version": "2.0",
        "User-Agent": BROWSER_UA,
        "Authorization": f"Bearer {token}",
    }
    resp = await session.get(f"{API_BASE_URL}{path}", headers=headers)
    resp.raise_for_status()
    return resp.json()


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
    body = data.get("body")
    if isinstance(body, list):
        print(f"  → {path.name} ({len(body)} item(s))")
    else:
        print(f"  → {path.name}")


if __name__ == "__main__":
    asyncio.run(main())
