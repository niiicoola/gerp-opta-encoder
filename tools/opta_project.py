"""Percorsi portabili condivisi dagli strumenti di preparazione Opta."""
import os
from pathlib import Path
import shutil
import re

ROOT = Path(__file__).resolve().parents[1]
FQBN = "arduino:mbed_opta:opta"
BUILD_PROFILE = "opta_lite_encoder"
SKETCH = ROOT / "firmware/opta_encoder_lan"


def platform_spec():
    specs = re.findall(r"^\s+- platform: (arduino:mbed_opta) \(([^)]+)\)\s*$",
                       (SKETCH / "sketch.yaml").read_text(), re.MULTILINE)
    if len(specs) != 1:
        raise ValueError("Versione del core Opta mancante o ambigua in sketch.yaml")
    platform, version = specs[0]
    return f"{platform}@{version}"


def find_cli(explicit=None):
    candidate = explicit or os.environ.get("ARDUINO_CLI") or shutil.which("arduino-cli")
    if not candidate:
        candidate = "/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli"
    resolved = shutil.which(str(candidate))
    if not resolved:
        raise ValueError("Arduino CLI non trovato: installarlo o impostare ARDUINO_CLI al percorso dell'eseguibile")
    return str(Path(resolved).resolve())


def config_file(explicit=None):
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not path.is_file():
            raise ValueError("Il file di configurazione Arduino indicato non esiste")
        return path
    path = ROOT / "arduino-cli.yaml"
    if not path.exists():
        import json
        directories = {"data": ".arduino-data", "downloads": ".arduino-staging", "user": ".arduino-user"}
        content = "directories:\n" + "".join(
            f"  {name}: {json.dumps(str(ROOT / directory))}\n" for name, directory in directories.items())
        with path.open("x") as stream:
            stream.write(content)
    return path
