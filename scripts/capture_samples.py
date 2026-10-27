"""Capture raw data.go.kr (NMC) XML samples for Chungju into docs/samples/.

Usage: python scripts/capture_samples.py
Reads EM_DATA_GO_KR_KEY (ER service) and optional EM_DATA_GO_KR_KEY_PHARMACY (pharmacy
service, falls back to the ER key) from the environment or .env. Keys are never printed or saved.
One run makes 5 + (number of ER hospitals) calls.
"""

from __future__ import annotations

import asyncio
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote, quote_plus, unquote

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.core.env import load_env  # noqa: E402

OUT = ROOT / "docs" / "samples"
TIMEOUT_S = 5.0
ER = "https://apis.data.go.kr/B552657/ErmctInfoInqireService"
PH = "https://apis.data.go.kr/B552657/ErmctInsttInfoInqireService"
LON, LAT = "127.93", "36.99"

# Tags to show one example value for, by role. First present tag wins.
ROLES: dict[str, list[str]] = {
    "id": ["hpid"],
    "name": ["dutyName"],
    "phone": ["dutyTel1", "dutyTel3"],
    "latitude": ["wgs84Lat", "latitude"],
    "longitude": ["wgs84Lon", "longitude"],
    "distance": ["distance"],
    "update time": ["hvidate"],
    "address": ["dutyAddr"],
}
HOURS = [f"dutyTime{d}{sc}" for d in range(1, 9) for sc in "sc"]


class CaptureError(Exception):
    pass


def secret_forms(keys: list[str]) -> set[str]:
    return {f for key in keys for f in (key, quote(key, safe=""), quote_plus(key)) if f}


def redact(text: str, keys: list[str]) -> str:
    for form in secret_forms(keys):
        text = text.replace(form, "***")
    return text


def check_result(xml_text: str) -> ET.Element:
    """Return the parsed root if resultCode is 00, else raise with only code and message."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        raise CaptureError("response is not XML") from None
    if root.tag == "OpenAPI_ServiceResponse":  # gateway error (key, quota, unknown operation)
        code = root.findtext(".//returnReasonCode") or "?"
        msg = root.findtext(".//returnAuthMsg") or root.findtext(".//errMsg") or "?"
        raise CaptureError(f"resultCode={code} resultMsg={msg}")
    code = root.findtext("./header/resultCode")
    if code != "00":
        raise CaptureError(f"resultCode={code} resultMsg={root.findtext('./header/resultMsg')}")
    return root


async def fetch(
    client: httpx.AsyncClient, url: str, params: dict[str, str], key: str, keys: list[str]
) -> tuple[str, ET.Element]:
    op = url.rsplit("/", 1)[-1]
    try:
        resp = await client.get(url, params={"serviceKey": key, **params})
    except httpx.HTTPError as e:  # the message would contain the URL with the key
        raise CaptureError(f"{op}: {type(e).__name__}") from None
    if resp.status_code != 200:
        raise CaptureError(f"{op}: HTTP {resp.status_code}")
    text = resp.text
    try:
        root = check_result(text)
    except CaptureError as e:
        raise CaptureError(f"{op}: {redact(str(e), keys)}") from None
    return text, root


def save(name: str, text: str, keys: list[str]) -> Path:
    leaked = any(form in text for form in secret_forms(keys))
    assert not leaked, f"{name}: response contains a service key, not saved"
    path = OUT / name
    path.write_text(text, encoding="utf-8")
    assert not any(form in path.read_text(encoding="utf-8") for form in secret_forms(keys))
    return path


def items(root: ET.Element) -> list[ET.Element]:
    return root.findall("./body/items/item")


def summarize(name: str, root: ET.Element, pharmacy: bool = False) -> None:
    its = items(root)
    print(f"\n== {name}")
    print(f"totalCount: {root.findtext('./body/totalCount')}  items in file: {len(its)}")
    if not its:
        return
    first = its[0]
    print(f"first item tags: {[child.tag for child in first]}")
    for role, tags in ROLES.items():
        tag = next((t for t in tags if first.find(t) is not None), None)
        shown = f"{tag} = {first.findtext(tag)!r}" if tag else f"absent (looked for {', '.join(tags)})"
        print(f"  {role:<12} {shown}")
    if pharmacy:
        hours = {t: first.findtext(t) for t in HOURS if first.find(t) is not None}
        print(f"  hours        {hours or 'absent'}")


def read_key(name: str) -> str:
    key = os.environ.get(name, "").strip()
    return unquote(key) if "%" in key else key  # an already-encoded key would be encoded twice by httpx


def hpids(root: ET.Element) -> list[str]:
    return [h for h in (it.findtext("hpid") for it in items(root)) if h]


async def main() -> int:
    load_env()
    er_key = read_key("EM_DATA_GO_KR_KEY")
    ph_key = read_key("EM_DATA_GO_KR_KEY_PHARMACY") or er_key
    if not er_key:
        print("EM_DATA_GO_KR_KEY is not set (put it in .env)")
        return 1
    keys = [er_key, ph_key]
    OUT.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        try:
            beds_xml, beds = await fetch(
                client, f"{ER}/getEmrrmRltmUsefulSckbdInfoInqire",
                {"STAGE1": "충청북도", "STAGE2": "충주시", "pageNo": "1", "numOfRows": "10"}, er_key, keys,
            )
            save("er_beds.xml", beds_xml, keys)

            loc_xml, loc = await fetch(
                client, f"{ER}/getEgytLcinfoInqire",
                {"WGS84_LON": LON, "WGS84_LAT": LAT, "pageNo": "1", "numOfRows": "10"}, er_key, keys,
            )
            save("er_locations.xml", loc_xml, keys)

            basics: dict[str, ET.Element] = {}
            for hpid in hpids(beds):
                basic_xml, basics[hpid] = await fetch(
                    client, f"{ER}/getEgytBassInfoInqire", {"HPID": hpid}, er_key, keys
                )
                save(f"er_basic_{hpid}.xml", basic_xml, keys)

            radius_xml, radius = await fetch(
                client, f"{PH}/getParmacyLcinfoInqire",
                {"WGS84_LON": LON, "WGS84_LAT": LAT, "pageNo": "1", "numOfRows": "10"}, ph_key, keys,
            )
            save("pharmacies_radius.xml", radius_xml, keys)

            list_xml, plist = await fetch(
                client, f"{PH}/getParmacyListInfoInqire",
                {"Q0": "충청북도", "Q1": "충주시", "pageNo": "1", "numOfRows": "10"}, ph_key, keys,
            )
            save("pharmacies_list.xml", list_xml, keys)
        except CaptureError as e:
            print(f"STOP {e}")
            return 1

    summarize("er_beds.xml", beds)
    summarize("er_locations.xml", loc)
    for hpid, basic in basics.items():
        summarize(f"er_basic_{hpid}.xml", basic)
    summarize("pharmacies_radius.xml", radius, pharmacy=True)
    summarize("pharmacies_list.xml", plist, pharmacy=True)

    bed_ids, loc_ids = hpids(beds), set(hpids(loc))
    print("\n== join key: hpid")
    for hpid in bed_ids:
        print(f"  {hpid}: in er_locations={hpid in loc_ids} in er_basic={bool(items(basics[hpid]))}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
