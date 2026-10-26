#!/usr/bin/env python3
"""Legge uno snapshot OPC UA coerente. Non scrive valori sul dispositivo."""
import argparse
import json
import logging
import sys
import time

from opcua import Client, ua

NAMESPACE = "urn:gerp:encoder:v1"
MAX_NODES_PER_READ = 8
FIELDS = (
    "Encoder.NetPosition", "Encoder.TotalPulses", "Encoder.Rpm",
    "Encoder.CountsPerRevolution", "Encoder.ProfileId", "Encoder.Simulation",
    "Encoder.TestMode", "Encoder.MeasurementValid",
    "Device.UptimeMs", "Device.TimeSynchronized",
)


def read_good(node):
    value = node.get_data_value()
    value.StatusCode.check()
    return value.Value.Value


def snapshot(client, allow_simulation=False, allow_test=False, diagnostics=False):
    namespace = client.get_namespace_index(NAMESPACE)
    node = lambda name: client.get_node(ua.NodeId(name, namespace))
    boot_node = node("Device.BootId")
    sequence_node = node("Encoder.SampleSequence")
    for _ in range(5):
        boot_before = read_good(boot_node)
        before = read_good(sequence_node)
        if before % 2:
            continue
        fields = FIELDS + (("Encoder.LevelA", "Encoder.LevelB", "Encoder.EdgesA", "Encoder.EdgesB",
                            "Encoder.InvalidTransitions", "Device.MeasurementStatus") if diagnostics else ())
        nodes = [node(name) for name in fields]
        # Blocchi piccoli: sul dispositivo in prova il blocco diagnostico da 16
        # nodi va in timeout. La sequenza prima/dopo conserva la coerenza tra blocchi.
        values = []
        for offset in range(0, len(nodes), MAX_NODES_PER_READ):
            batch = nodes[offset:offset + MAX_NODES_PER_READ]
            received = client.uaclient.get_attributes([n.nodeid for n in batch], ua.AttributeIds.Value)
            if len(received) != len(batch):
                raise ValueError("Risposta OPC UA incompleta")
            values.extend(received)
        result = {}
        for name, value in zip(fields, values):
            value.StatusCode.check()
            result[name] = value.Value.Value
        after = read_good(sequence_node)
        boot_after = read_good(boot_node)
        if before != after or after % 2 or boot_before != boot_after:
            continue
        if result["Encoder.Simulation"] and not allow_simulation:
            raise ValueError("SIMULAZIONE: dati esclusi dalla produzione; usare --allow-simulation per il test")
        if not result["Encoder.Simulation"] and (result["Encoder.TestMode"] or not result["Encoder.MeasurementValid"]) and not allow_test:
            raise ValueError("TEST NON VALIDATO: dati esclusi dalla produzione; usare --allow-test per la diagnostica")
        result["Device.BootId"] = boot_after
        result["Encoder.SampleSequence"] = after
        # JSON conserva i 64 bit come stringhe, anche per eventuali consumer JavaScript.
        for name in ("Encoder.NetPosition", "Encoder.TotalPulses", "Device.UptimeMs"):
            result[name] = str(result[name])
        return result
    raise RuntimeError("Impossibile ottenere un campione coerente; ripetere la lettura")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("endpoint", help="opc.tcp://IP_OPTA:4840")
    parser.add_argument("--allow-simulation", action="store_true")
    parser.add_argument("--allow-test", action="store_true")
    parser.add_argument("--diagnostics", action="store_true", help="legge anche livelli A/B, fronti ed errori del lettore reale")
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--interval", type=float, default=1)
    args = parser.parse_args()
    if args.samples < 1 or args.interval < 0:
        parser.error("samples deve essere positivo e interval non negativo")
    logging.basicConfig(level=logging.ERROR)
    client = Client(args.endpoint, timeout=5)
    connected = False
    try:
        client.connect()
        connected = True
        for i in range(args.samples):
            if i:
                time.sleep(args.interval)
            print(json.dumps(snapshot(client, args.allow_simulation, args.allow_test, args.diagnostics)), flush=True)
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc) or type(exc).__name__}), file=sys.stderr)
        return 1
    finally:
        if connected:
            try:
                client.disconnect()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
