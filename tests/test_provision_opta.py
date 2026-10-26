"""Controlli di destinazione, integrità e qualità senza hardware o rete."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import provision_opta as provision
import build_opta_lan as build_tool
import opta_profiles

PROJECT = Path(__file__).resolve().parents[1]


class ProvisionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "profiles").mkdir()
        self.profile = json.loads((PROJECT / "profiles/e38s6g5-600b-g24n-x4.json").read_text())
        (self.root / "profiles/e38s6g5-600b-g24n-x4.json").write_text(json.dumps(self.profile))
        self.lika = json.loads((PROJECT / "profiles/lika-ir65-2500-x4.json").read_text())
        (self.root / "profiles/lika-ir65-2500-x4.json").write_text(json.dumps(self.lika))
        self.device = json.loads((PROJECT / "devices/example.json").read_text())
        self.device.update(usb_serial="SERIAL001", firmware_version="0.3.3-lan", encoder_profile=self.profile["profile_id"])
        self.path = self.root / "device.json"
        self.path.write_text(json.dumps(self.device))
        self.root_patch = patch.object(provision, "ROOT", self.root)
        self.root_patch.start()

    def tearDown(self):
        self.root_patch.stop()
        self.temp.cleanup()

    def listing(self, serial="SERIAL001", board=provision.FQBN):
        return {"detected_ports": [{"port": {"address": "/dev/ttyACM0", "protocol": "serial",
                                            "properties": {"serialNumber": serial}},
                                    "matching_boards": [{"fqbn": board}]}]}

    def release(self):
        directory = self.root / "release"
        directory.mkdir()
        content = (struct.pack("<II", 0x24080000, 0x08040041) + b"GERP_OPTA_OTA_V1\0" + b"0.3.3-lan\0"
                   + self.profile["firmware_profile_id"].encode() + b"\0" + bytes(400))
        (directory / "firmware.bin").write_bytes(content)
        metadata = {"version": "0.3.3-lan", "board": provision.FQBN,
                    "encoder_profile": self.profile["profile_id"], "qualification": "diagnostic_only",
                    "counts_per_revolution": self.profile["counts_per_revolution"],
                    "firmware_profile_id": self.profile["firmware_profile_id"],
                    "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
        (directory / "manifest.json").write_text(json.dumps(metadata))
        return directory

    def snapshots(self):
        state = {"firmware": "0.3.3-lan", "ota_ready": True, "boot_id": "a" * 32}
        sample = {"Device.BootId": "a" * 32, "Encoder.ProfileId": self.profile["firmware_profile_id"],
                  "Encoder.CountsPerRevolution": 2400, "Encoder.Simulation": False,
                  "Encoder.TestMode": True, "Encoder.MeasurementValid": False,
                  "Encoder.NetPosition": "-10", "Encoder.TotalPulses": "100",
                  "Device.UptimeMs": "1000", "Encoder.InvalidTransitions": 0}
        later = {**sample, "Encoder.NetPosition": "-20", "Encoder.TotalPulses": "110", "Device.UptimeMs": "2000"}
        return state, [sample, later]

    def test_rejects_unknown_board_profile_credentials_and_extra_fields(self):
        for key, value in (("model", "OTHER"), ("encoder_profile", "../../unsafe"),
                           ("maintenance_url", "http://user:password@device:8080"),
                           ("opcua_endpoint", "http://device:4840"), ("schema_version", True),
                           ("password", "never-store-here")):
            device = {**self.device, key: value}
            self.path.write_text(json.dumps(device))
            with self.subTest(key=key), self.assertRaises(ValueError):
                provision.load_device(self.path)

    def test_selects_only_unique_serial_and_correct_board(self):
        self.assertEqual(provision.selected_port(self.listing(), "SERIAL001", "/dev/ttyACM0"), "/dev/ttyACM0")
        for listing, serial, address in ((self.listing(), "OTHER", None),
                                         (self.listing(), "SERIAL001", "/dev/ttyACM9"),
                                         (self.listing(board="other:board"), "SERIAL001", None),
                                         (self.listing(), None, None)):
            with self.assertRaises(ValueError):
                provision.selected_port(listing, serial, address)
        ambiguous = self.listing()
        ambiguous["detected_ports"] *= 2
        with self.assertRaises(ValueError):
            provision.selected_port(ambiguous, "SERIAL001")

    def test_release_integrity_and_profile_binding(self):
        directory = self.release()
        provision.check_release(directory, self.device)
        with self.assertRaises(ValueError):
            provision.check_release(directory, {**self.device, "firmware_version": "0.3.4-lan"})
        image = directory / "firmware.bin"
        image.write_bytes(image.read_bytes()[:-1] + b"x")
        with self.assertRaises(ValueError):
            provision.check_release(directory, self.device)

    def test_install_dry_run_does_not_discover_or_write_device(self):
        args = argparse.Namespace(release=self.release(), port="/dev/ttyACM0", apply=False,
                                  init_ota=True, arduino_cli=None, config_file=None)
        with patch.object(provision, "find_cli", return_value="arduino-cli"), \
                patch.object(provision, "config_file", return_value=self.root / "config.yaml"), \
                patch.object(provision, "board_list") as discover, patch.object(provision.subprocess, "run") as run:
            provision.install(args, self.device)
            discover.assert_not_called()
            run.assert_not_called()

    def test_install_wrong_serial_blocks_upload(self):
        args = argparse.Namespace(release=self.release(), port="/dev/ttyACM0", apply=True,
                                  init_ota=False, arduino_cli=None, config_file=None)
        with patch.object(provision, "find_cli", return_value="arduino-cli"), \
                patch.object(provision, "config_file", return_value=self.root / "config.yaml"), \
                patch.object(provision, "board_list", return_value=self.listing(serial="OTHER")), \
                patch.object(provision.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                provision.install(args, self.device)
            run.assert_not_called()

    def test_install_matching_serial_uses_pinned_platform_and_records_unverified_state(self):
        args = argparse.Namespace(release=self.release(), port="/dev/ttyACM0", apply=True,
                                  init_ota=False, arduino_cli=None, config_file=None)
        with patch.object(provision, "find_cli", return_value="arduino-cli"), \
                patch.object(provision, "config_file", return_value=self.root / "config.yaml"), \
                patch.object(provision, "board_list", return_value=self.listing()), \
                patch.object(provision.subprocess, "run") as run, patch.object(provision, "report") as record:
            provision.install(args, self.device)
            command = run.call_args.args[0]
            self.assertEqual(command[command.index("--profile") + 1], "opta_lite_encoder")
            self.assertEqual(command[command.index("--port") + 1], "/dev/ttyACM0")
            self.assertEqual(record.call_args.args[2]["state"], "uploaded_not_yet_verified")

    def test_reading_preserves_sign_and_does_not_qualify_physical_measurement(self):
        state, samples = self.snapshots()
        result = provision.assess_samples(self.device, self.profile, state, samples, state)
        self.assertEqual(result["position"], "-20")
        self.assertEqual(result["state"], "diagnostic_read_ok")
        self.assertFalse(result["remote_hardware_identity_verified"])

    def test_reading_rejects_reboot_stale_samples_new_errors_and_wrong_profiles(self):
        state, samples = self.snapshots()
        for key, value in (("Device.BootId", "b" * 32), ("Device.UptimeMs", "1000"),
                           ("Encoder.TotalPulses", "99"), ("Encoder.InvalidTransitions", 1),
                           ("Encoder.Simulation", True), ("Encoder.ProfileId", "different"),
                           ("Encoder.CountsPerRevolution", 600), ("Encoder.MeasurementValid", True)):
            changed = deepcopy(samples)
            changed[1][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                provision.assess_samples(self.device, self.profile, state, changed, state)
        with self.assertRaises(ValueError):
            provision.assess_samples(self.device, self.profile, state, samples, {**state, "boot_id": "b" * 32})

    def test_new_device_never_overwrites_existing_serial_or_record(self):
        args = argparse.Namespace(device_id="opta-001", serial="SERIAL001", site="Test", machine_id=None,
                                  encoder_profile=self.profile["profile_id"],
                                  version="0.3.3-lan", maintenance_url="http://192.0.2.10:8080",
                                  opcua_endpoint="opc.tcp://192.0.2.10:4840")
        provision.new_device(args)
        original = (self.root / "devices/local/opta-001.json").read_bytes()
        with self.assertRaises(ValueError):
            provision.new_device(args)
        args.device_id = "opta-002"
        with self.assertRaises(ValueError):
            provision.new_device(args)
        self.assertEqual((self.root / "devices/local/opta-001.json").read_bytes(), original)

    def test_existing_release_is_not_rebuilt_or_uploaded(self):
        (self.root / ".build/releases/0.3.3-lan").mkdir(parents=True)
        with patch.object(build_tool, "ROOT", self.root), \
                patch.object(sys, "argv", ["build_opta_lan.py", "--version", "0.3.3-lan", "--encoder-profile", self.profile["profile_id"], "--upload", "192.0.2.10"]), \
                patch.object(build_tool.subprocess, "run") as run:
            self.assertEqual(build_tool.main(), 1)
            run.assert_not_called()

    def test_lika_and_prototype_remain_distinct_profiles(self):
        self.path.write_text(json.dumps({**self.device, "encoder_profile": "lika-ir65-2500-x4"}))
        device, profile = provision.load_device(self.path)
        self.assertEqual(profile["counts_per_revolution"], 10000)
        directory = self.release()
        with self.assertRaises(ValueError):
            provision.check_release(directory, device)
        state, samples = self.snapshots()
        with self.assertRaises(ValueError):
            provision.assess_samples(device, profile, state, samples, state)

    def test_incoherent_profile_cannot_generate_an_installed_configuration(self):
        self.lika["counts_per_revolution"] = 2400
        (self.root / "profiles/lika-ir65-2500-x4.json").write_text(json.dumps(self.lika))
        with self.assertRaises(ValueError):
            opta_profiles.load_profile("lika-ir65-2500-x4", self.root)


if __name__ == "__main__":
    unittest.main()
