#!/usr/bin/env python3
"""Legge per un tempo limitato la console USB dell'Opta, senza inviare comandi."""
import argparse
import array
import fcntl
import os
import select
import termios
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("port", nargs="?", default="/dev/cu.usbmodem1101")
parser.add_argument("--seconds", type=float, default=15)
args = parser.parse_args()
if args.seconds <= 0:
    parser.error("seconds deve essere positivo")
end = time.monotonic() + args.seconds
waiting = False
try:
    while time.monotonic() < end:
        fd = None
        original = None
        try:
            fd = os.open(args.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
            original = termios.tcgetattr(fd)
            settings = termios.tcgetattr(fd)
            settings[0] = 0
            settings[1] = 0
            settings[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
            settings[3] = 0
            settings[4] = settings[5] = termios.B115200
            settings[6][termios.VMIN] = 0
            settings[6][termios.VTIME] = 0
            termios.tcsetattr(fd, termios.TCSANOW, settings)
            fcntl.ioctl(fd, termios.TIOCMBIS, array.array("i", [termios.TIOCM_DTR]))
            print("\nMonitor encoder collegato. Ctrl+C per terminare.\n", flush=True)
            waiting = False
            while time.monotonic() < end:
                remaining = max(0, end - time.monotonic())
                if select.select([fd], [], [], min(1, remaining))[0]:
                    data = os.read(fd, 4096)
                    if not data:
                        raise OSError("Console USB disconnessa")
                    print(data.decode("utf-8", errors="replace"), end="", flush=True)
        except PermissionError:
            print("Accesso USB negato: chiudere eventuali altri monitor seriali e verificare i permessi.", flush=True)
            break
        except (OSError, termios.error):
            if not waiting:
                print("\nUSB non disponibile: attendo che l'Opta venga ricollegato.\n", flush=True)
                waiting = True
            time.sleep(min(1, max(0, end - time.monotonic())))
        finally:
            if fd is not None:
                if original is not None:
                    try:
                        termios.tcsetattr(fd, termios.TCSANOW, original)
                    except (OSError, termios.error):
                        pass
                os.close(fd)
except KeyboardInterrupt:
    print("\nMonitor terminato.")
