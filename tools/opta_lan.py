#!/usr/bin/env python3
"""Stato, upload firmato e verifica riavvio dell'Opta, via LAN o VPN instradata."""
import argparse
import hashlib
import http.client
import json
from pathlib import Path
import struct
import subprocess
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = "GERP_OPTA_OTA_V1"
MAX_IMAGE = 0x1C0000


def endpoint(value):
    value = value if "://" in value else "http://" + value + ":8080"
    parsed = urlsplit(value)
    if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("Usare l'indirizzo LAN/VPN del dispositivo, senza credenziali o percorso")
    return value.rstrip("/")


def status(base, timeout=10):
    # Nessun proxy di sistema: indirizzo raggiunto direttamente tramite LAN/VPN.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(base + "/status", timeout=timeout) as response:
        raw = response.read(8193)
    if len(raw) > 8192:
        raise ValueError("Risposta troppo grande")
    data = json.loads(raw)
    if data.get("protocol") != PROTOCOL:
        raise ValueError("Il dispositivo non espone il protocollo OTA previsto")
    return data


def validate_image(data):
    if not 256 <= len(data) <= MAX_IMAGE:
        raise ValueError("Dimensione firmware non valida")
    sp, reset = struct.unpack_from("<II", data)
    if sp & 7 or not 0x24000000 < sp <= 0x24080000 or not reset & 1 or not 0x08040001 <= reset < 0x08040000 + len(data):
        raise ValueError("Il BIN non contiene i vettori di un'applicazione Opta M7")
    if PROTOCOL.encode() not in data:
        raise ValueError("Il firmware non conserva il supporto OTA: caricamento rifiutato")


def signed_headers(data, nonce, key):
    if len(nonce) != 32 or any(ch not in "0123456789abcdef" for ch in nonce):
        raise ValueError("Sfida del dispositivo non valida")
    digest = hashlib.sha256(data).hexdigest()
    message = f"{PROTOCOL}\n{nonce}\n{len(data)}\n{digest}\n".encode()
    signature = subprocess.run(["openssl", "dgst", "-sha256", "-sign", str(key)],
                               input=message, capture_output=True, check=True).stdout
    return {"Content-Length": str(len(data)), "Content-Type": "application/octet-stream",
            "X-Firmware-SHA256": digest, "X-OTA-Nonce": nonce,
            "X-OTA-Signature": signature.hex(), "Connection": "close"}


def post_image(base, data, headers):
    parsed = urlsplit(base)
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=150)
    try:
        conn.request("POST", "/update", body=data, headers=headers)
        response = conn.getresponse()
        result = json.loads(response.read(8192))
        if response.status != 202 or not result.get("accepted"):
            raise RuntimeError(f"Aggiornamento rifiutato (HTTP {response.status}): {result}")
        return result
    finally:
        conn.close()


def upload(base, image, key, expected_version):
    data = image.read_bytes()
    validate_image(data)
    if expected_version.encode() + b"\0" not in data:
        raise ValueError("La versione attesa non compare nel firmware")
    if not key.is_file():
        raise ValueError("Manca la chiave privata locale di firma")
    before = status(base)
    if not before.get("ota_ready"):
        raise RuntimeError(f"Memoria OTA non pronta: {before.get('storage_result')}")
    print(json.dumps({"event": "upload", "bytes": len(data), "from": before["firmware"],
                      "to": expected_version}), flush=True)
    result = post_image(base, data, signed_headers(data, before["nonce"], key))
    print(json.dumps(result), flush=True)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        time.sleep(2)
        try:
            after = status(base, timeout=3)
        except (OSError, ValueError, http.client.HTTPException):
            continue
        if after["boot_id"] == before["boot_id"]:
            continue
        if after["firmware"] != expected_version:
            raise RuntimeError(f"Riavvio rilevato ma versione diversa: {after['firmware']}")
        if not after.get("ota_ready"):
            raise RuntimeError("Nuovo firmware avviato, ma supporto OTA non pronto")
        print(json.dumps({"event": "verified", "status": after}), flush=True)
        return after
    raise RuntimeError("Nessuna conferma del nuovo firmware: verificare USB prima di riprovare")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host", help="IP Opta oppure http://IP:8080")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    update = sub.add_parser("upload")
    update.add_argument("image", type=Path)
    update.add_argument("--expect-version", required=True)
    update.add_argument("--key", type=Path, default=ROOT / ".secrets/opta-ota-private.pem")
    args = parser.parse_args()
    try:
        base = endpoint(args.host)
        if args.command == "status":
            print(json.dumps(status(base), indent=2))
        else:
            upload(base, args.image, args.key, args.expect_version)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError, http.client.HTTPException) as exc:
        parser.exit(1, f"Errore: {exc}\n")


if __name__ == "__main__":
    main()
