#!/usr/bin/env python3
"""Genera una chiave di firma locale; sul dispositivo va solo la chiave pubblica."""
from pathlib import Path
import os
import subprocess

ROOT = Path(__file__).resolve().parents[1]
secrets = ROOT / ".secrets"
secrets.mkdir(mode=0o700, exist_ok=True)
private = secrets / "opta-ota-private.pem"
public = secrets / "opta-ota-public.pem"
if not private.exists():
    fd = os.open(private, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    subprocess.run(["openssl", "genpkey", "-algorithm", "EC", "-pkeyopt",
                    "ec_paramgen_curve:prime256v1", "-out", str(private)], check=True)
if private.stat().st_size == 0:
    raise SystemExit("Chiave privata vuota: correggere prima di proseguire.")
os.chmod(private, 0o600)
subprocess.run(["openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)], check=True)
pem = public.read_text().strip() + "\n"
header = ROOT / "firmware/opta_encoder_lan/OtaPublicKey.h"
header.parent.mkdir(parents=True, exist_ok=True)
header.write_text('#pragma once\n// Chiave pubblica; la chiave privata resta sul Mac.\n'
                  'static const char OTA_PUBLIC_KEY[] = R"KEY(' + pem + ')KEY";\n')
print("Chiave di firma pronta; nessuna chiave privata inclusa nel firmware.")
