#!/usr/bin/env python3
"""Controlla la postazione. --install prepara core Arduino e client Python locale."""
import argparse
import json
import shlex
import shutil
import subprocess
import sys

from opta_project import ROOT, find_cli, config_file, platform_spec


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true", help="installa il core Opta fissato e prepara .venv")
    parser.add_argument("--arduino-cli")
    args = parser.parse_args()
    try:
        cli = find_cli(args.arduino_cli)
        version = subprocess.run([cli, "version"], check=True, text=True, capture_output=True).stdout.strip()
        print(json.dumps({"arduino_cli": cli, "version": version, "openssl": shutil.which("openssl"),
                          "python": sys.version.split()[0], "project": str(ROOT)}, indent=2), flush=True)
        if sys.version_info < (3, 9):
            raise ValueError("È richiesto Python 3.9 o successivo")
        if not shutil.which("openssl"):
            raise ValueError("Installare OpenSSL prima di generare o usare le chiavi OTA")
        python = ROOT / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        config = config_file() if args.install else ROOT / "arduino-cli.yaml"
        commands = [[cli, "core", "update-index", "--config-file", str(config)],
                    [cli, "core", "install", platform_spec(), "--config-file", str(config)]]
        if not python.exists():
            commands.append([sys.executable, "-m", "venv", str(ROOT / ".venv")])
        commands.append([str(python), "-m", "pip", "install", "-r", str(ROOT / "tools/requirements.txt")])
        for command in commands:
            print(shlex.join(command), flush=True)
            if args.install:
                subprocess.run(command, check=True)
        print("Il core per il riconoscimento USB e le dipendenze di compilazione sono fissati in sketch.yaml.")
        if not args.install:
            print("Solo controllo: nessuna dipendenza installata. Per preparare il client usare --install.")
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
