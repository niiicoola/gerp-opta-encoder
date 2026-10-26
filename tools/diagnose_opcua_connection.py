#!/usr/bin/env python3
"""Verifica, senza scritture, in quale fase si interrompe una connessione OPC UA."""
import argparse
import logging
from opcua import Client, ua
from read_encoder_opcua import FIELDS

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("endpoint")
args = parser.parse_args()
logging.basicConfig(level=logging.ERROR)
client = Client(args.endpoint, timeout=4)
channel = False
session = False
stage = "TCP"
try:
    for stage, action in (
        ("TCP", client.connect_socket),
        ("HELLO OPC UA", client.send_hello),
        ("CANALE OPC UA", client.open_secure_channel),
        ("CREAZIONE SESSIONE", client.create_session),
        ("ATTIVAZIONE SESSIONE", client.activate_session),
    ):
        print(f"Verifica {stage}...", flush=True)
        action()
        channel = channel or stage == "CANALE OPC UA"
        session = session or stage == "CREAZIONE SESSIONE"
        print(f"{stage}: OK", flush=True)
    print("Connessione OPC UA completa: OK", flush=True)
    stage = "LETTURA NAMESPACE"
    print(f"Verifica {stage}...", flush=True)
    namespaces = client.get_namespace_array()
    print(f"{stage}: {namespaces}", flush=True)
    index = namespaces.index("urn:gerp:encoder:v1")
    for name in ("Device.BootId", "Encoder.SampleSequence", "Encoder.LevelA", "Encoder.LevelB", "Encoder.NetPosition"):
        stage = f"LETTURA {name}"
        print(f"Verifica {stage}...", flush=True)
        print(client.get_node(f"ns={index};s={name}").get_value(), flush=True)
    stage = "LETTURE MULTIPLE"
    fields = FIELDS + ("Encoder.LevelA", "Encoder.LevelB", "Encoder.EdgesA", "Encoder.EdgesB", "Encoder.InvalidTransitions", "Device.MeasurementStatus")
    ids = [ua.NodeId(name, index) for name in fields]
    for size in (2, 4, 10, len(ids)):
        stage = f"BLOCCO DA {size} NODI"
        print(f"Verifica {stage}...", flush=True)
        values = client.uaclient.get_attributes(ids[:size], ua.AttributeIds.Value)
        print(f"{stage}: {len(values)} risultati", flush=True)
except Exception as exc:
    print(f"{stage}: ERRORE {type(exc).__name__}: {exc}", flush=True)
    raise SystemExit(1)
finally:
    if session:
        try:
            client.close_session()
        except Exception:
            pass
    if channel:
        try:
            client.close_secure_channel()
        except Exception:
            pass
    client.disconnect_socket()
