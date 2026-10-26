"""Profili encoder diagnostici usati da compilazione e collaudo."""
import json
from pathlib import Path
import re

from opta_project import ROOT


def load_profile(identifier, root=None):
    if not isinstance(identifier, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,95}", identifier):
        raise ValueError("Identificativo profilo encoder non valido")
    profile = json.loads(((root or ROOT) / "profiles" / f"{identifier}.json").read_text())
    if (not isinstance(profile, dict) or profile.get("schema_version") != 1 or profile.get("profile_id") != identifier
            or profile.get("compatible_board") != "AFX00003" or profile.get("qualification") != "diagnostic_only"):
        raise ValueError("Profilo non compatibile con Opta Lite diagnostico")
    ppr, counts, multiplier = (profile.get(name) for name in
                              ("pulses_per_revolution", "counts_per_revolution", "decoding_multiplier"))
    if (type(ppr) is not int or not 1 <= ppr <= 1000000 or type(multiplier) is not int or multiplier != 4
            or type(counts) is not int or counts != ppr * multiplier):
        raise ValueError("Il decoder implementa x4: PPR e conteggi/giro devono essere coerenti")
    firmware_id = profile.get("firmware_profile_id")
    if not isinstance(firmware_id, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,127}", firmware_id):
        raise ValueError("Identificativo OPC UA del profilo non valido")
    return profile


def profile_header(profile):
    return ("#pragma once\n// Generato dal profilo della release; non modificare manualmente.\n"
            f"#define GERP_ENCODER_PPR {profile['pulses_per_revolution']}u\n"
            f"#define GERP_ENCODER_COUNTS_PER_REVOLUTION {profile['counts_per_revolution']}u\n"
            f"#define GERP_ENCODER_PROFILE_ID {json.dumps(profile['firmware_profile_id'])}\n"
            'static_assert(GERP_ENCODER_COUNTS_PER_REVOLUTION == GERP_ENCODER_PPR * 4u, "Decoder x4 richiesto");\n')
