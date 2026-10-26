#!/usr/bin/env python3
"""Prove negative sulla vera Opta: nessun firmware valido viene applicato."""
import argparse
import hashlib
import http.client
import json
from pathlib import Path
from urllib.parse import urlsplit
import opta_lan as lan

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("host")
args = parser.parse_args()
base = lan.endpoint(args.host)
before = lan.status(base)
key = lan.ROOT / ".secrets/opta-ota-private.pem"


def expect(label, body, headers, code):
    target = urlsplit(base)
    conn = http.client.HTTPConnection(target.hostname, target.port or 80, timeout=20)
    try:
        conn.request("POST", "/update", body=body, headers=headers)
        reply = conn.getresponse()
        result = reply.read(2048).decode()
        if reply.status != code:
            raise RuntimeError(f"{label}: HTTP {reply.status}, atteso {code}: {result}")
        print(json.dumps({"test": label, "http": reply.status, "result": result}), flush=True)
    finally:
        conn.close()


payload = bytes(512)
expect("unsigned", payload, {"Content-Length": "512"}, 403)
state = lan.status(base)
headers = lan.signed_headers(payload, state["nonce"], key)
headers["X-OTA-Signature"] = "00" * 70
expect("invalid_signature", payload, headers, 403)
expect("oversize", b"", {"Content-Length": str(lan.MAX_IMAGE + 1)}, 400)
if before["ota_ready"]:
    state = lan.status(base)
    headers = lan.signed_headers(payload, state["nonce"], key)
    expect("signed_wrong_hash", b"X" + payload[1:], headers, 422)
    expect("replayed_nonce", payload, headers, 403)
    state = lan.status(base)
    expect("signed_wrong_board", payload, lan.signed_headers(payload, state["nonce"], key), 422)
after = lan.status(base)
if after["boot_id"] != before["boot_id"] or after["firmware"] != before["firmware"]:
    raise RuntimeError("La prova negativa ha riavviato o modificato il firmware")
print("PASS: aggiornamenti non validi rifiutati, nessun riavvio.")
