"""Verifiche con un vero server OPC UA locale, senza hardware."""
import importlib.util
import logging
from pathlib import Path
import socket
import unittest

from opcua import Client, Server, ua

spec = importlib.util.spec_from_file_location(
    "reader", Path(__file__).resolve().parents[1] / "tools/read_encoder_opcua.py")
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)


class SnapshotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        logging.getLogger().setLevel(logging.ERROR)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        cls.endpoint = f"opc.tcp://127.0.0.1:{port}"
        cls.server = Server()
        cls.server.set_endpoint(cls.endpoint)
        cls.server.register_namespace("urn:test:unrelated")
        cls.ns = cls.server.register_namespace(reader.NAMESPACE)
        obj = cls.server.get_objects_node().add_object(cls.ns, "Encoder")
        cls.nodes = {}
        fields = {
            "Encoder.NetPosition": (-9007199254740993, ua.VariantType.Int64),
            "Encoder.TotalPulses": (9007199254740993, ua.VariantType.UInt64),
            "Encoder.Rpm": (-60.0, ua.VariantType.Double),
            "Encoder.CountsPerRevolution": (600, ua.VariantType.UInt32),
            "Encoder.ProfileId": ("simulation-600-x1-v1", ua.VariantType.String),
            "Encoder.Simulation": (True, ua.VariantType.Boolean),
            "Encoder.TestMode": (False, ua.VariantType.Boolean),
            "Encoder.MeasurementValid": (True, ua.VariantType.Boolean),
            "Encoder.SampleSequence": (2, ua.VariantType.UInt32),
            "Device.BootId": ("test-boot", ua.VariantType.String),
            "Device.UptimeMs": (1234, ua.VariantType.UInt64),
            "Device.TimeSynchronized": (False, ua.VariantType.Boolean),
            "Encoder.LevelA": (False, ua.VariantType.Boolean),
            "Encoder.LevelB": (True, ua.VariantType.Boolean),
            "Encoder.EdgesA": (100, ua.VariantType.UInt32),
            "Encoder.EdgesB": (101, ua.VariantType.UInt32),
            "Encoder.InvalidTransitions": (0, ua.VariantType.UInt32),
            "Device.MeasurementStatus": (1, ua.VariantType.UInt32),
        }
        for name, (value, kind) in fields.items():
            cls.nodes[name] = obj.add_variable(ua.NodeId(name, cls.ns), name, ua.Variant(value, kind))
        cls.server.start()
        cls.client = Client(cls.endpoint)
        cls.client.connect()

    @classmethod
    def tearDownClass(cls):
        cls.client.disconnect()
        cls.server.stop()

    def test_namespace_sign_and_64_bit_precision(self):
        self.assertNotEqual(self.ns, 2)
        value = reader.snapshot(self.client, allow_simulation=True)
        self.assertEqual(value["Encoder.NetPosition"], "-9007199254740993")
        self.assertEqual(value["Encoder.TotalPulses"], "9007199254740993")
        self.assertEqual(value["Encoder.Rpm"], -60.0)

    def test_simulation_is_rejected_by_default(self):
        with self.assertRaisesRegex(ValueError, "SIMULAZIONE"):
            reader.snapshot(self.client)

    def test_incomplete_snapshot_is_rejected(self):
        sequence = self.nodes["Encoder.SampleSequence"]
        sequence.set_value(ua.Variant(3, ua.VariantType.UInt32))
        try:
            with self.assertRaisesRegex(RuntimeError, "coerente"):
                reader.snapshot(self.client, True)
        finally:
            sequence.set_value(ua.Variant(2, ua.VariantType.UInt32))

    def test_bad_quality_is_not_zero(self):
        rpm = self.nodes["Encoder.Rpm"]
        bad = ua.DataValue(ua.Variant(0.0, ua.VariantType.Double))
        bad.StatusCode = ua.StatusCode(ua.StatusCodes.BadSensorFailure)
        rpm.set_data_value(bad)
        try:
            with self.assertRaises(ua.UaStatusCodeError):
                reader.snapshot(self.client, True)
        finally:
            rpm.set_value(ua.Variant(-60.0, ua.VariantType.Double))

    def test_remote_write_is_rejected(self):
        remote = self.client.get_node(ua.NodeId("Encoder.NetPosition", self.ns))
        with self.assertRaises(ua.UaStatusCodeError):
            remote.set_value(ua.Variant(99, ua.VariantType.Int64))

    def test_real_diagnostic_data_is_rejected_by_default(self):
        simulation = self.nodes["Encoder.Simulation"]
        test_mode = self.nodes["Encoder.TestMode"]
        simulation.set_value(False)
        test_mode.set_value(True)
        try:
            with self.assertRaisesRegex(ValueError, "TEST NON VALIDATO"):
                reader.snapshot(self.client)
            self.assertTrue(reader.snapshot(self.client, allow_test=True)["Encoder.TestMode"])
        finally:
            simulation.set_value(True)
            test_mode.set_value(False)

    def test_diagnostics_use_bounded_reads(self):
        original = self.client.uaclient.get_attributes
        batch_sizes = []
        def bounded(nodes, attribute):
            batch_sizes.append(len(nodes))
            self.assertLessEqual(len(nodes), reader.MAX_NODES_PER_READ)
            return original(nodes, attribute)
        self.client.uaclient.get_attributes = bounded
        try:
            result = reader.snapshot(self.client, allow_simulation=True, diagnostics=True)
            self.assertEqual(batch_sizes, [8, 8])
            self.assertEqual(result["Encoder.EdgesB"], 101)
            self.assertTrue(result["Encoder.LevelB"])
        finally:
            self.client.uaclient.get_attributes = original


if __name__ == "__main__":
    unittest.main()
