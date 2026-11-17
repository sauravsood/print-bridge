"""Small web server: upload a PDF, preview it as labels, print to the TSC printer.

Standard library only. Run with:  python3 -m print_bridge.server
"""

from __future__ import annotations

import json
import os
import re
import secrets
import tempfile
import threading
import time
from dataclasses import fields
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import printer
from .render import LabelSpec, RenderError, render_pdf

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DATA = Path(os.environ.get("PRINT_BRIDGE_DATA", ROOT.parent / "data"))
SETTINGS_FILE = DATA / "settings.json"
MAX_UPLOAD = 25 * 1024 * 1024
JOB_TTL = 3600

DEFAULTS = {
    "printer_host": os.environ.get("PRINTER_HOST", ""),
    "printer_port": int(os.environ.get("PRINTER_PORT", "9100")),
    "width_mm": 101.6,
    "height_mm": 152.4,
    "media": "gap",
    "gap_mm": 3.0,
    "density": 8,
    "speed": 4,
    "direction": 1,
    "threshold": 160,
    "trim": True,
    "rotate": True,
}

_lock = threading.Lock()
_jobs: dict[str, dict] = {}


def load_settings() -> dict:
    s = dict(DEFAULTS)
    try:
        s.update({k: v for k, v in json.loads(SETTINGS_FILE.read_text()).items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return s


def save_settings(update: dict) -> dict:
    s = load_settings()
    for k, v in update.items():
        if k not in DEFAULTS:
            continue
        kind = type(DEFAULTS[k])
        try:
            if kind is bool:
                s[k] = bool(v)
            elif kind is int:
                s[k] = int(v)
            elif kind is float:
                s[k] = float(v)
            else:
                s[k] = str(v).strip()
        except (TypeError, ValueError):
            raise ValueError(f"Bad value for {k}")
    if s["media"] not in ("gap", "bline", "continuous"):
        raise ValueError("media must be gap, bline or continuous")
    if not (20 <= s["width_mm"] <= 110 and 10 <= s["height_mm"] <= 1000):
        raise ValueError("Label size is outside what the TA220 can print (max width 108 mm)")
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=2))
    tmp.replace(SETTINGS_FILE)
    return s


def label_spec(s: dict) -> LabelSpec:
    return LabelSpec(width_mm=s["width_mm"], height_mm=s["height_mm"], threshold=s["threshold"],
                     trim=s["trim"], rotate=s["rotate"])


def print_settings(s: dict) -> printer.PrintSettings:
    names = {f.name for f in fields(printer.PrintSettings)}
    return printer.PrintSettings(**{k: v for k, v in s.items() if k in names})


def _gc_jobs() -> None:
    now = time.time()
    with _lock:
        for k in [k for k, j in _jobs.items() if now - j["created"] > JOB_TTL]:
            del _jobs[k]


def _test_job(s: dict) -> bytes:
    ps = print_settings(s)
    head = printer.build_job([], ps)
    w = round(s["width_mm"] / 25.4 * 203)
    h = round(s["height_mm"] / 25.4 * 203)
    body = (
        "CLS\r\n"
        f"BOX 16,16,{w - 16},{h - 16},4\r\n"
        'TEXT 40,60,"4",0,1,1,"Print bridge OK"\r\n'
        f'TEXT 40,120,"3",0,1,1,"Label {s["width_mm"]:g} x {s["height_mm"]:g} mm"\r\n'
        f'TEXT 40,170,"3",0,1,1,"{time.strftime("%Y-%m-%d %H:%M")}"\r\n'
        f'BARCODE 40,240,"128",100,1,0,2,4,"BUTTERBEINGS"\r\n'
        "PRINT 1,1\r\n"
    )
    return head + body.encode()


class Handler(BaseHTTPRequestHandler):
    server_version = "PrintBridge/1.0"

    # ---- helpers -------------------------------------------------------
    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json")

    def _error(self, msg: str, code: int = 400) -> None:
        self._json({"error": msg}, code)

    def _body(self, limit: int) -> bytes | None:
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            self._error("Empty request")
            return None
        if n > limit:
            self._error("File is too large (max 25 MB)", HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            return None
        return self.rfile.read(n)

    def _json_body(self) -> dict | None:
        raw = self._body(64 * 1024) if int(self.headers.get("Content-Length") or 0) else b"{}"
        if raw is None:
            return None
        try:
            obj = json.loads(raw or b"{}")
            return obj if isinstance(obj, dict) else {}
        except ValueError:
            self._error("Bad JSON")
            return None

    def _printer_addr(self, s: dict) -> tuple[str, int] | None:
        if not s["printer_host"]:
            self._error("Set the printer's IP address in Settings first", 409)
            return None
        return s["printer_host"], s["printer_port"]

    def log_message(self, fmt, *args):  # quieter journal: path + status only
        print(f"{self.command} {self.path.split('?')[0]} {args[1] if len(args) > 1 else ''}", flush=True)

    # ---- routes --------------------------------------------------------
    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
        if path == "/manifest.webmanifest":
            return self._send(200, (STATIC / "manifest.webmanifest").read_bytes(), "application/manifest+json")
        if path == "/icon.svg":
            return self._send(200, (STATIC / "icon.svg").read_bytes(), "image/svg+xml")
        if path == "/api/settings":
            return self._json(load_settings())
        if path == "/api/status":
            s = load_settings()
            if not s["printer_host"]:
                return self._json({"online": False, "ready": False, "message": "Printer IP not set"})
            return self._json(printer.status(s["printer_host"], s["printer_port"]))
        if path == "/api/discover":
            return self._json({"hosts": printer.discover(load_settings()["printer_port"])})
        m = re.fullmatch(r"/api/jobs/([A-Za-z0-9_-]+)/(\d+)\.png", path)
        if m:
            job = _jobs.get(m[1])
            n = int(m[2])
            if not job or not 1 <= n <= len(job["pages"]):
                return self._error("Not found", 404)
            return self._send(200, printer.to_png(job["pages"][n - 1]), "image/png")
        return self._error("Not found", 404)

    def do_POST(self):
        # Browsers can't add this header cross-site without a CORS preflight,
        # which we never approve, so it blocks drive-by form posts.
        if self.headers.get("X-Print-Bridge") != "1":
            return self._error("Missing X-Print-Bridge header", 403)
        path = self.path.split("?")[0]
        s = load_settings()

        if path == "/api/settings":
            body = self._json_body()
            if body is None:
                return
            try:
                return self._json(save_settings(body))
            except ValueError as e:
                return self._error(str(e))

        if path == "/api/jobs":
            data = self._body(MAX_UPLOAD)
            if data is None:
                return
            if not data.startswith(b"%PDF"):
                return self._error("That file isn't a PDF")
            _gc_jobs()
            with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
                f.write(data)
                f.flush()
                try:
                    pages = render_pdf(f.name, label_spec(s))
                except RenderError as e:
                    return self._error(str(e), 422)
            jid = secrets.token_urlsafe(9)
            with _lock:
                _jobs[jid] = {"created": time.time(), "pages": pages, "settings": s}
            return self._json({"id": jid, "pages": len(pages),
                               "previews": [f"/api/jobs/{jid}/{i + 1}.png" for i in range(len(pages))]})

        m = re.fullmatch(r"/api/jobs/([A-Za-z0-9_-]+)/print", path)
        if m:
            job = _jobs.get(m[1])
            if not job:
                return self._error("This upload expired. Please choose the PDF again.", 404)
            body = self._json_body()
            if body is None:
                return
            addr = self._printer_addr(s)
            if not addr:
                return
            want = body.get("pages") or list(range(1, len(job["pages"]) + 1))
            try:
                chosen = [job["pages"][int(n) - 1] for n in want if 1 <= int(n) <= len(job["pages"])]
                copies = int(body.get("copies", 1))
            except (TypeError, ValueError):
                return self._error("Bad page list or copies")
            if not chosen:
                return self._error("No pages selected")
            payload = printer.build_job(chosen, print_settings(job["settings"]), copies)
            try:
                printer.send(*addr, payload)
            except OSError as e:
                return self._error(f"Couldn't send to printer: {e.strerror or e}", 502)
            return self._json({"ok": True, "labels": len(chosen) * max(1, copies)})

        if path in ("/api/test", "/api/calibrate", "/api/feed"):
            addr = self._printer_addr(s)
            if not addr:
                return
            payload = {
                "/api/test": lambda: _test_job(s),
                "/api/calibrate": lambda: printer.build_job([], print_settings(s)) + b"GAPDETECT\r\n",
                "/api/feed": lambda: printer.build_job([], print_settings(s)) + b"FORMFEED\r\n",
            }[path]()
            try:
                printer.send(*addr, payload)
            except OSError as e:
                return self._error(f"Couldn't send to printer: {e.strerror or e}", 502)
            return self._json({"ok": True})

        return self._error("Not found", 404)


def main() -> None:
    listen = os.environ.get("LISTEN", "127.0.0.1:8080")
    host, _, port = listen.rpartition(":")
    srv = ThreadingHTTPServer((host or "127.0.0.1", int(port)), Handler)
    print(f"print-bridge listening on http://{listen}  (settings: {SETTINGS_FILE})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
