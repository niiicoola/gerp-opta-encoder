"""Controlli del client e firma con OpenSSL reale, senza dispositivo."""
import importlib.util
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("lan", Path(__file__).resolve().parents[1] / "tools/opta_lan.py")
lan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lan)


class LanOtaTest(unittest.TestCase):
    def image(self):
        return struct.pack("<II", 0x24080000, 0x08040041) + lan.PROTOCOL.encode() + bytes(400)

    def test_rejects_wrong_board_or_missing_remote_support(self):
        for content in (bytes(512), struct.pack("<II", 0x20010000, 0x08000041) + bytes(504),
                        struct.pack("<II", 0x24080000, 0x08040041) + bytes(504)):
            with self.assertRaises(ValueError):
                lan.validate_image(content)
        lan.validate_image(self.image())

    def test_rejects_truncated_or_oversize_images(self):
        for data in (b"x", bytes(lan.MAX_IMAGE + 1)):
            with self.assertRaises(ValueError):
                lan.validate_image(data)

    def test_signed_message_binds_nonce_size_and_content(self):
        with tempfile.TemporaryDirectory() as temp:
            key, pub, signature = (Path(temp) / x for x in ("key.pem", "pub.pem", "signature"))
            subprocess.run(["openssl", "genpkey", "-algorithm", "EC", "-pkeyopt",
                            "ec_paramgen_curve:prime256v1", "-out", str(key)], check=True, capture_output=True)
            subprocess.run(["openssl", "pkey", "-in", str(key), "-pubout", "-out", str(pub)], check=True, capture_output=True)
            headers = lan.signed_headers(self.image(), "a" * 32, key)
            signature.write_bytes(bytes.fromhex(headers["X-OTA-Signature"]))
            message = f"{lan.PROTOCOL}\n{'a' * 32}\n{len(self.image())}\n{headers['X-Firmware-SHA256']}\n".encode()
            command = ["openssl", "dgst", "-sha256", "-verify", str(pub), "-signature", str(signature)]
            self.assertEqual(subprocess.run(command, input=message, capture_output=True).returncode, 0)
            for altered in (message.replace(b"a" * 32, b"b" * 32), message + b"tampered"):
                self.assertNotEqual(subprocess.run(command, input=altered, capture_output=True).returncode, 0)

    def test_rejects_malformed_challenge_and_endpoint(self):
        with self.assertRaises(ValueError):
            lan.signed_headers(self.image(), "wrong", Path("unused"))
        for value in ("https://device", "http://user:password@device", "http://device/path"):
            with self.assertRaises(ValueError):
                lan.endpoint(value)


if __name__ == "__main__":
    unittest.main()
