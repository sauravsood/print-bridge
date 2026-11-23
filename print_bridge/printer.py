"""TSPL job building and raw TCP (port 9100) talk with a TSC printer."""

from __future__ import annotations

import concurrent.futures
import ipaddress
import socket
import struct
import zlib
from dataclasses import dataclass

from .render import Bitmap

CONNECT_TIMEOUT = 4.0


@dataclass
class PrintSettings:
    width_mm: float = 101.6
    height_mm: float = 152.4
    media: str = "gap"        # gap | bline | continuous
    gap_mm: float = 3.0
    density: int = 8          # 0-15
    speed: int = 4            # inches per second
    direction: int = 1        # 1 = label comes out top first


def _num(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


def build_job(pages: list[Bitmap], s: PrintSettings, copies: int = 1) -> bytes:
    copies = max(1, min(int(copies), 999))
    head = [
        f"SIZE {_num(s.width_mm)} mm,{_num(s.height_mm)} mm",
        {
            "gap": f"GAP {_num(s.gap_mm)} mm,0 mm",
            "bline": f"BLINE {_num(s.gap_mm)} mm,0 mm",
            "continuous": "GAP 0,0",
        }.get(s.media, f"GAP {_num(s.gap_mm)} mm,0 mm"),
        f"DENSITY {max(0, min(15, int(s.density)))}",
        f"SPEED {max(1, min(6, int(s.speed)))}",
        f"DIRECTION {1 if s.direction else 0},0",
        "REFERENCE 0,0",
        "OFFSET 0 mm",
        "SET TEAR ON",
    ]
    out = bytearray(("\r\n".join(head) + "\r\n").encode())
    for bmp in pages:
        out += b"CLS\r\n"
        out += f"BITMAP 0,0,{bmp.row_bytes},{bmp.height},0,".encode()
        out += bmp.data()
        out += f"\r\nPRINT 1,{copies}\r\n".encode()
    return bytes(out)


def send(host: str, port: int, payload: bytes) -> None:
    with socket.create_connection((host, port), timeout=CONNECT_TIMEOUT) as sock:
        sock.settimeout(30)
        sock.sendall(payload)


# Reply byte to <ESC>!? (TSPL status poll). 0 means ready.
_STATUS_BITS = [
    (0x01, "head open"),
    (0x02, "paper jam"),
    (0x04, "out of labels"),
    (0x08, "out of ribbon"),
    (0x10, "paused"),
    (0x20, "printing"),
    (0x80, "other error"),
]


def _unreachable(host: str, port: int, e: OSError) -> dict:
    """Plain-English status for a printer the bridge can't connect to."""
    reason = e.strerror or str(e) or type(e).__name__
    if isinstance(e, ConnectionRefusedError):
        hint = ("Something answered at this address, but it isn't the printer. "
                "Open Printer settings and tap Find.")
    else:
        # No route to host / timed out: nothing is answering at that address.
        hint = ("Check the printer is switched on and its cable is plugged into the main router, "
                "then open Printer settings and tap Find. Its address may have changed.")
    return {"online": False, "ready": False, "message": "Can't reach printer",
            "detail": f"{host}:{port}: {reason}", "hint": hint}


def status(host: str, port: int) -> dict:
    try:
        with socket.create_connection((host, port), timeout=CONNECT_TIMEOUT) as sock:
            sock.settimeout(2.5)
            sock.sendall(b"\x1b!?")
            try:
                b = sock.recv(1)
            except socket.timeout:
                return {"online": True, "ready": None, "message": "Connected (printer did not report status)"}
    except OSError as e:
        return _unreachable(host, port, e)
    if not b:
        return {"online": True, "ready": None, "message": "Connected (no status reply)"}
    code = b[0]
    if code == 0:
        return {"online": True, "ready": True, "message": "Ready", "code": 0}
    problems = [name for bit, name in _STATUS_BITS if code & bit]
    busy_only = problems == ["printing"]
    return {"online": True, "ready": busy_only, "message": ", ".join(problems).capitalize() or f"Status {code}", "code": code}


def _local_networks() -> list[ipaddress.IPv4Network]:
    nets = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # no packet is sent; picks the LAN interface
            ip = s.getsockname()[0]
        nets.append(ipaddress.ip_network(f"{ip}/24", strict=False))
    except OSError:
        pass
    return nets


def discover(port: int = 9100, timeout: float = 0.6) -> list[str]:
    """Find hosts on the local /24 with the raw print port open."""
    hosts = [str(h) for net in _local_networks() for h in net.hosts()]

    def probe(h: str) -> str | None:
        try:
            with socket.create_connection((h, port), timeout=timeout):
                return h
        except OSError:
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=64) as ex:
        return [h for h in ex.map(probe, hosts) if h]


def to_png(bmp: Bitmap) -> bytes:
    """1-bit grayscale PNG for the browser preview."""
    raw = b"".join(b"\x00" + row for row in bmp.rows)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", bmp.width, bmp.height, 1, 0, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
