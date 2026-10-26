#!/usr/bin/env python3
"""Richiede via USB il provisioning OTA: il firmware rifiuta memoria non vuota."""
import argparse
import array
import fcntl
import os
import select
import termios
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("port")
args = parser.parse_args()
fd = os.open(args.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
original = termios.tcgetattr(fd)
settings = termios.tcgetattr(fd)
settings[0] = settings[1] = settings[3] = 0
settings[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
settings[4] = settings[5] = termios.B115200
termios.tcsetattr(fd, termios.TCSANOW, settings)
try:
    fcntl.ioctl(fd, termios.TIOCMBIS, array.array("i", [termios.TIOCM_DTR]))
    time.sleep(1)
    os.write(fd, b"INIT_OTA_IF_EMPTY\n")
    deadline = time.monotonic() + 45
    pending = ""
    while time.monotonic() < deadline:
        if select.select([fd], [], [], 1)[0]:
            data = os.read(fd, 4096)
            if not data:
                raise SystemExit("USB disconnessa")
            pending += data.decode(errors="replace")
            while "\n" in pending:
                line, pending = pending.split("\n", 1)
                print(line.rstrip(), flush=True)
                if line.startswith("OTA_INIT_RESULT="):
                    raise SystemExit(0 if line.strip() == "OTA_INIT_RESULT=0" else 1)
    raise SystemExit("Nessuna conferma del provisioning entro 45 secondi")
finally:
    termios.tcsetattr(fd, termios.TCSANOW, original)
    os.close(fd)
