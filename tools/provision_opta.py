#!/usr/bin/env python3
"""Registro, installazione USB esplicita e verifica diagnostica degli Opta Lite."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
from urllib.parse import urlsplit

from opta_project import ROOT, FQBN, BUILD_PROFILE, SKETCH, config_file, find_cli
from opta_lan import status, validate_image
from opta_profiles import load_profile

DEVICE_FIELDS = {"schema_version", "device_id", "model", "usb_serial", "site", "gerp_machine_id",
                 "encoder_profile", "firmware_version", "maintenance_url", "opcua_endpoint"}


def read_json(path):
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError(f"Oggetto JSON atteso: {path}")
    return value


def check_url(value, scheme):
    if not isinstance(value, str):
        raise ValueError(f"Indirizzo {scheme} richiesto")
    parsed = urlsplit(value)
    if (parsed.scheme != scheme or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.path not in ("", "/") or parsed.query or parsed.fragment
            or parsed.port is None or not 1 <= parsed.port <= 65535):
        raise ValueError(f"Indirizzo {scheme} non valido: specificare host e porta senza credenziali o percorso")
    return value.rstrip("/")


def load_device(path):
    device = read_json(path)
    if set(device) != DEVICE_FIELDS or type(device["schema_version"]) is not int or device["schema_version"] != 1:
        raise ValueError("Campi del registro dispositivo non validi; partire da devices/example.json")
    if not isinstance(device["device_id"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", device["device_id"]):
        raise ValueError("device_id: usare al massimo 64 lettere minuscole, numeri e trattini")
    if device["model"] != "AFX00003":
        raise ValueError("Questa versione supporta solo Opta Lite AFX00003")
    serial = device["usb_serial"]
    if serial is not None and (not isinstance(serial, str) or not re.fullmatch(r"[A-Za-z0-9_:-]{1,128}", serial)):
        raise ValueError("Seriale USB non valido")
    if device["site"] is not None and (not isinstance(device["site"], str) or len(device["site"]) > 200):
        raise ValueError("Sede non valida")
    machine = device["gerp_machine_id"]
    if machine is not None and (type(machine) is not int or machine < 1):
        raise ValueError("gerp_machine_id deve essere un intero positivo oppure null")
    if not isinstance(device["firmware_version"], str) or not re.fullmatch(r"\d+\.\d+\.\d+-lan", device["firmware_version"]):
        raise ValueError("Versione firmware non valida")
    check_url(device["maintenance_url"], "http")
    check_url(device["opcua_endpoint"], "opc.tcp")
    profile = load_profile(device["encoder_profile"], ROOT)
    return device, profile


def new_device(args):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", args.device_id):
        raise ValueError("Identificativo dispositivo non valido")
    directory = ROOT / "devices/local"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{args.device_id}.json"
    device = {"schema_version": 1, "device_id": args.device_id, "model": "AFX00003", "usb_serial": args.serial,
              "site": args.site, "gerp_machine_id": args.machine_id, "encoder_profile": args.encoder_profile,
              "firmware_version": args.version, "maintenance_url": check_url(args.maintenance_url, "http"),
              "opcua_endpoint": check_url(args.opcua_endpoint, "opc.tcp")}
    for existing in directory.glob("*.json"):
        other = read_json(existing)
        if other.get("device_id") == args.device_id or (args.serial and other.get("usb_serial") == args.serial):
            raise ValueError("Identificativo o seriale già registrato: aggiornare il file esistente")
    # Validazione prima della creazione: non lasciare un registro parziale se
    # l'operatore fornisce un valore non ammesso.
    import tempfile
    with tempfile.TemporaryDirectory() as temp:
        temporary = Path(temp) / "device.json"
        temporary.write_text(json.dumps(device))
        load_device(temporary)
    with path.open("x") as stream:
        json.dump(device, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    print(path)


def selected_port(listing, serial, address=None):
    if not serial or serial == "DA_COMPILARE":
        raise ValueError("Registrare il seriale USB prima dell'installazione; usare il comando discover")
    matches = []
    for detected in listing.get("detected_ports", []):
        port = detected.get("port", {})
        actual_serial = port.get("properties", {}).get("serialNumber")
        board_ok = any(board.get("fqbn") == FQBN for board in detected.get("matching_boards", []))
        if actual_serial == serial and (address is None or port.get("address") == address):
            if not board_ok or port.get("protocol") != "serial":
                raise ValueError("Il seriale corrisponde, ma la scheda non è riconosciuta come Opta via USB")
            matches.append(port["address"])
    if len(matches) != 1:
        raise ValueError("Nessuna corrispondenza USB univoca per seriale e porta; nessun caricamento eseguito")
    return matches[0]


def board_list(cli, config):
    result = subprocess.run([cli, "board", "list", "--json", "--config-file", str(config)],
                            check=True, text=True, capture_output=True)
    return json.loads(result.stdout)


def check_release(directory, device):
    directory = Path(directory)
    metadata = read_json(directory / "manifest.json")
    profile = load_profile(device["encoder_profile"], ROOT)
    image = directory / "firmware.bin"
    content = image.read_bytes()
    validate_image(content)
    if (metadata.get("version") != device["firmware_version"] or metadata.get("board") != FQBN
            or metadata.get("encoder_profile") != device["encoder_profile"]
            or metadata.get("qualification") != "diagnostic_only"
            or metadata.get("counts_per_revolution") != profile["counts_per_revolution"]
            or metadata.get("firmware_profile_id") != profile["firmware_profile_id"]
            or metadata.get("bytes") != len(content)
            or metadata.get("sha256") != hashlib.sha256(content).hexdigest()
            or device["firmware_version"].encode() + b"\0" not in content
            or profile["firmware_profile_id"].encode() + b"\0" not in content):
        raise ValueError("Release non coerente con scheda, versione, profilo o hash; nessun caricamento eseguito")
    return image.resolve(), metadata


def report(device, operation, result):
    stamp = datetime.now(timezone.utc)
    directory = ROOT / "reports" / device["device_id"]
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{stamp.strftime('%Y%m%dT%H%M%S%fZ')}-{operation}.json"
    value = {"device_id": device["device_id"], "operation": operation,
             "time_utc": stamp.isoformat(), "production_qualified": False, **result}
    with path.open("x") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"report": str(path), **value}, ensure_ascii=False, indent=2), flush=True)


def install(args, device):
    image, metadata = check_release(args.release, device)
    if not device["usb_serial"] or device["usb_serial"] == "DA_COMPILARE":
        raise ValueError("Compilare usb_serial con il seriale ottenuto da discover")
    cli = find_cli(args.arduino_cli)
    config = config_file(args.config_file)
    command = [cli, "upload", "--fqbn", FQBN, "--profile", BUILD_PROFILE, "--config-file", str(config),
               "--port", args.port, "--input-file", str(image), str(SKETCH)]
    print("Il caricamento riavvia l'Opta e azzera i contatori diagnostici.", flush=True)
    print(shlex.join(command), flush=True)
    if not args.apply:
        print("PIANO: nessuna comunicazione USB, nessun caricamento. Usare --apply per installare.")
        if args.init_ota:
            print("Dopo il caricamento sarà richiesta l'inizializzazione OTA, consentita solo se la memoria è vuota.")
        return
    selected_port(board_list(cli, config), device["usb_serial"], args.port)
    subprocess.run(command, check=True)
    if args.init_ota:
        deadline = time.monotonic() + 30
        port = None
        while time.monotonic() < deadline:
            time.sleep(2)
            try:
                port = selected_port(board_list(cli, config), device["usb_serial"])
                break
            except ValueError:
                continue
        if port is None:
            raise ValueError("USB non ricomparsa con lo stesso seriale dopo il caricamento; fermare e verificare")
        subprocess.run([sys.executable, str(ROOT / "tools/init_ota_storage.py"), port], check=True)
    report(device, "install-usb", {"state": "uploaded_not_yet_verified", "usb_serial": device["usb_serial"],
                                   "firmware_version": metadata["version"], "sha256": metadata["sha256"],
                                   "ota_initialization_requested": args.init_ota})


def assess_samples(device, profile, before, samples, after):
    if not samples:
        raise ValueError("Nessun campione OPC UA ricevuto")
    if (before.get("firmware") != device["firmware_version"] or after.get("firmware") != device["firmware_version"]
            or not before.get("ota_ready") or not after.get("ota_ready")):
        raise ValueError("Versione firmware diversa dal registro o memoria OTA non pronta")
    boot = before.get("boot_id")
    if not isinstance(boot, str) or not re.fullmatch(r"[a-f0-9]{32}", boot) or after.get("boot_id") != boot:
        raise ValueError("Riavvio durante la verifica o BootId non valido")
    previous = None
    errors = None
    for sample in samples:
        if (sample.get("Device.BootId") != boot or sample.get("Encoder.ProfileId") != profile["firmware_profile_id"]
                or sample.get("Encoder.CountsPerRevolution") != profile["counts_per_revolution"]
                or sample.get("Encoder.Simulation") is not False
                or sample.get("Encoder.TestMode") is not True or sample.get("Encoder.MeasurementValid") is not False):
            raise ValueError("Identità di avvio, profilo o stato diagnostico OPC UA diverso da quello atteso")
        position = int(sample["Encoder.NetPosition"])
        total = int(sample["Encoder.TotalPulses"])
        uptime = int(sample["Device.UptimeMs"])
        invalid = int(sample["Encoder.InvalidTransitions"])
        if total < 0 or uptime < 0 or invalid < 0:
            raise ValueError("Contatori diagnostici non validi")
        if errors is not None and invalid != errors:
            raise ValueError("Transizioni non valide variate durante la verifica")
        if previous is not None and (total < previous[0] or uptime <= previous[1]):
            raise ValueError("Campioni non aggiornati o conteggio totale diminuito durante lo stesso avvio")
        errors = invalid
        previous = total, uptime
    return {"state": "diagnostic_read_ok", "firmware_version": after["firmware"], "boot_id": boot,
            "samples": len(samples), "position": str(position), "total": str(total), "invalid_transitions": errors,
            "remote_hardware_identity_verified": False,
            "limits": ["Identità hardware remota non esposta dal firmware attuale: verificare il percorso di rete e il registro USB.",
                       "Questo rapporto verifica la comunicazione; precisione, velocità massima e persistenza richiedono collaudi separati."]}


def verify(args, device, profile):
    if not args.allow_test:
        raise ValueError("Il firmware attuale è diagnostico: specificare --allow-test; non abilita l'uso in produzione")
    base = check_url(args.maintenance_url or device["maintenance_url"], "http")
    endpoint = check_url(args.opcua_endpoint or device["opcua_endpoint"], "opc.tcp")
    before = status(base)
    command = [sys.executable, str(ROOT / "tools/read_encoder_opcua.py"), endpoint,
               "--allow-test", "--diagnostics", "--samples", str(args.samples), "--interval", "1"]
    print(shlex.join(command), flush=True)
    response = subprocess.run(command, capture_output=True, text=True, timeout=30 + args.samples * 20)
    if response.returncode:
        raise ValueError("Lettura OPC UA fallita: " + response.stderr.strip()[-2000:])
    samples = [json.loads(line) for line in response.stdout.splitlines() if line.strip()]
    if len(samples) != args.samples:
        raise ValueError("Numero di campioni diverso da quello richiesto")
    after = status(base)
    result = assess_samples(device, profile, before, samples, after)
    report(device, "verify", result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    new = sub.add_parser("new", help="crea un registro locale; non comunica con l'Opta")
    new.add_argument("device_id")
    new.add_argument("--serial")
    new.add_argument("--site")
    new.add_argument("--machine-id", type=int)
    new.add_argument("--version", required=True)
    new.add_argument("--encoder-profile", required=True)
    new.add_argument("--maintenance-url", required=True)
    new.add_argument("--opcua-endpoint", required=True)
    discover = sub.add_parser("discover", help="mostra schede e seriali USB; non carica firmware")
    discover.add_argument("--arduino-cli")
    discover.add_argument("--config-file", type=Path)
    check = sub.add_parser("validate", help="controllo locale del registro e del profilo")
    check.add_argument("device", type=Path)
    check.add_argument("--release", type=Path, help="controlla anche il pacchetto, senza comunicare con l'Opta")
    usb = sub.add_parser("install-usb", help="mostra il piano; scrive solo con --apply")
    usb.add_argument("device", type=Path)
    usb.add_argument("--release", type=Path, required=True)
    usb.add_argument("--port", required=True)
    usb.add_argument("--apply", action="store_true")
    usb.add_argument("--init-ota", action="store_true", help="solo prima installazione su memoria vuota")
    usb.add_argument("--arduino-cli")
    usb.add_argument("--config-file", type=Path)
    check_net = sub.add_parser("verify", help="legge HTTP e OPC UA; non scrive sul dispositivo né in GERP")
    check_net.add_argument("device", type=Path)
    check_net.add_argument("--allow-test", action="store_true")
    check_net.add_argument("--samples", type=int, default=3)
    check_net.add_argument("--maintenance-url")
    check_net.add_argument("--opcua-endpoint")
    args = parser.parse_args()
    try:
        if args.command == "new":
            new_device(args)
        elif args.command == "discover":
            print(json.dumps(board_list(find_cli(args.arduino_cli), config_file(args.config_file)), indent=2))
        else:
            device, profile = load_device(args.device)
            if args.command == "validate":
                result = {"state": "registry_valid", "device_id": device["device_id"],
                          "encoder_profile": profile["profile_id"], "production_qualified": False}
                if args.release:
                    image, metadata = check_release(args.release, device)
                    result.update(state="release_valid", image=str(image), sha256=metadata["sha256"])
                print(json.dumps(result, indent=2))
            elif args.command == "install-usb":
                install(args, device)
            else:
                if not 2 <= args.samples <= 600:
                    raise ValueError("Per la verifica usare da 2 a 600 campioni")
                verify(args, device, profile)
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        print(f"Errore: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
