#!/usr/bin/env python3
"""Compila e archivia una versione immutabile; --upload la applica via rete."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from opta_project import ROOT, FQBN, BUILD_PROFILE, SKETCH, config_file, find_cli
from opta_profiles import load_profile, profile_header


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="numero.numero.numero-lan, diverso per ogni release")
    parser.add_argument("--encoder-profile", required=True, help="profilo JSON in profiles/ senza estensione")
    parser.add_argument("--upload", metavar="IP_O_URL", help="applica via LAN o tunnel e riavvia l'Opta")
    parser.add_argument("--arduino-cli")
    parser.add_argument("--config-file", type=Path)
    parser.add_argument("--key", type=Path, default=ROOT / ".secrets/opta-ota-private.pem")
    args = parser.parse_args()
    try:
        if not re.fullmatch(r"\d+\.\d+\.\d+-lan", args.version):
            raise ValueError("Versione attesa: numero.numero.numero-lan")
        release = ROOT / ".build/releases" / args.version
        if release.exists():
            raise ValueError("La release esiste già: usare il BIN archiviato oppure scegliere una nuova versione")
        profile = load_profile(args.encoder_profile)
        if not (SKETCH / "OtaPublicKey.h").is_file():
            raise ValueError("Manca la chiave pubblica: eseguire tools/provision_ota_key.py sulla postazione autorizzata")
        cli = find_cli(args.arduino_cli)
        config = config_file(args.config_file)
        build = ROOT / ".build/opta_encoder_lan"
        (SKETCH / "BuildInfo.h").write_text(f'#pragma once\n#define GERP_FIRMWARE_VERSION "{args.version}"\n')
        (SKETCH / "EncoderProfile.h").write_text(profile_header(profile))
        subprocess.run([cli, "compile", "--profile", BUILD_PROFILE, "--config-file", str(config),
                        "--build-path", str(build), str(SKETCH)], check=True)
        image = build / "opta_encoder_lan.ino.bin"
        from opta_lan import validate_image
        validate_image(image.read_bytes())
        release.mkdir(parents=True, exist_ok=False)
        saved = release / "firmware.bin"
        shutil.copyfile(image, saved)
        manifest = {"version": args.version, "board": FQBN, "build_profile": BUILD_PROFILE,
                    "encoder_profile": profile["profile_id"], "qualification": profile["qualification"],
                    "counts_per_revolution": profile["counts_per_revolution"],
                    "firmware_profile_id": profile["firmware_profile_id"],
                    "sha256": hashlib.sha256(saved.read_bytes()).hexdigest(), "bytes": saved.stat().st_size}
        (release / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        shutil.copyfile(SKETCH / "sketch.yaml", release / "sketch.yaml")
        (release / "encoder-profile.json").write_text(json.dumps(profile, indent=2, ensure_ascii=False) + "\n")
        print(f"Firmware pronto: {saved}", flush=True)
        if args.upload:
            subprocess.run([sys.executable, str(ROOT / "tools/opta_lan.py"), args.upload, "upload", str(saved),
                            "--key", str(args.key), "--expect-version", args.version], check=True)
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
