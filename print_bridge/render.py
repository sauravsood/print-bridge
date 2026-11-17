"""Turn PDF pages into 1-bit label bitmaps sized for the printer.

Only needs poppler-utils (pdfinfo, pdftoppm), so it runs on a stock
Raspberry Pi OS install with no pip packages.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

POPPLER_TIMEOUT = 60  # seconds per call


class RenderError(Exception):
    pass


@dataclass
class Bitmap:
    """1-bit image. Each row is packed MSB-first, 0 = black, 1 = white.

    That bit order is what both TSPL BITMAP and 1-bit PNG expect.
    """

    width: int
    height: int
    rows: list[bytes]

    @property
    def row_bytes(self) -> int:
        return (self.width + 7) // 8

    def data(self) -> bytes:
        return b"".join(self.rows)


@dataclass
class LabelSpec:
    width_mm: float = 101.6   # 4 inch
    height_mm: float = 152.4  # 6 inch
    dpi: int = 203            # TSC TA220
    threshold: int = 160      # gray < threshold prints black
    trim: bool = True         # crop to the printed area before fitting
    rotate: bool = True       # rotate landscape content onto a portrait label
    margin_mm: float = 1.5

    @property
    def width_dots(self) -> int:
        return round(self.width_mm / 25.4 * self.dpi)

    @property
    def height_dots(self) -> int:
        return round(self.height_mm / 25.4 * self.dpi)

    @property
    def margin_dots(self) -> int:
        return round(self.margin_mm / 25.4 * self.dpi)


def _run(args: list[str]) -> bytes:
    try:
        out = subprocess.run(args, capture_output=True, timeout=POPPLER_TIMEOUT, check=False)
    except FileNotFoundError as e:
        raise RenderError(f"{args[0]} not found: install poppler-utils") from e
    except subprocess.TimeoutExpired as e:
        raise RenderError("PDF took too long to render") from e
    if out.returncode != 0:
        msg = out.stderr.decode(errors="replace").strip().splitlines()
        raise RenderError(msg[-1] if msg else f"{args[0]} failed")
    return out.stdout


def page_sizes(pdf_path: str) -> list[tuple[float, float]]:
    """(width, height) in points for every page, as pdftoppm will render it."""
    info = _run(["pdfinfo", "-f", "1", "-l", "9999", pdf_path]).decode(errors="replace")
    sizes: dict[int, list[float]] = {}
    rots: dict[int, int] = {}
    for m in re.finditer(r"^Page\s+(\d+)\s+size:\s+([\d.]+)\s+x\s+([\d.]+)", info, re.M):
        sizes[int(m[1])] = [float(m[2]), float(m[3])]
    for m in re.finditer(r"^Page\s+(\d+)\s+rot:\s+(\d+)", info, re.M):
        rots[int(m[1])] = int(m[2]) % 360
    if not sizes:
        m = re.search(r"^Pages:\s+(\d+)", info, re.M)
        raise RenderError("Could not read page sizes" if m else "Not a readable PDF")
    result = []
    for n in sorted(sizes):
        w, h = sizes[n]
        if rots.get(n, 0) in (90, 270):
            w, h = h, w
        result.append((w, h))
    return result


def _parse_pgm(data: bytes) -> tuple[int, int, bytes]:
    # P5 header: magic, width, height, maxval, separated by whitespace.
    m = re.match(rb"P5\s+(\d+)\s+(\d+)\s+(\d+)\s", data)
    if not m:
        raise RenderError("Unexpected output from pdftoppm")
    w, h, maxval = int(m[1]), int(m[2]), int(m[3])
    if maxval != 255:
        raise RenderError("Unexpected PGM depth")
    pixels = data[m.end(): m.end() + w * h]
    if len(pixels) != w * h:
        raise RenderError("Truncated render")
    return w, h, pixels


def _render_gray(pdf_path: str, page: int, dpi: float, crop: tuple[int, int, int, int] | None = None):
    args = ["pdftoppm", "-gray", "-aa", "yes", "-aaVector", "yes", "-f", str(page), "-l", str(page), "-r", f"{dpi:.4f}"]
    if crop:
        x, y, w, h = crop
        args += ["-x", str(x), "-y", str(y), "-W", str(max(1, w)), "-H", str(max(1, h))]
    args.append(pdf_path)
    return _parse_pgm(_run(args))


def _content_box(w: int, h: int, px: bytes, threshold: int) -> tuple[int, int, int, int] | None:
    """Bounding box (x0, y0, x1, y1) of dark pixels, or None for a blank page."""
    rows = [y for y in range(h) if px[y * w:(y + 1) * w].translate(None, bytes(range(threshold, 256)))]
    if not rows:
        return None
    y0, y1 = rows[0], rows[-1] + 1
    x0, x1 = w, 0
    for y in range(y0, y1):
        row = px[y * w:(y + 1) * w]
        for i, v in enumerate(row):
            if v < threshold:
                x0 = min(x0, i)
                break
        for i in range(w - 1, -1, -1):
            if row[i] < threshold:
                x1 = max(x1, i + 1)
                break
    return x0, y0, x1, y1


def _rotate_cw(w: int, h: int, px: bytes) -> tuple[int, int, bytes]:
    # New row r is old column r read bottom to top.
    return h, w, b"".join(px[r::w][::-1] for r in range(w))


def render_page(pdf_path: str, page: int, size_pt: tuple[float, float], spec: LabelSpec) -> Bitmap:
    pw, ph = size_pt
    # Content box in points.
    bx, by, bw, bh = 0.0, 0.0, pw, ph
    if spec.trim:
        w, h, px = _render_gray(pdf_path, page, 72)  # 1 px == 1 pt
        box = _content_box(w, h, px, spec.threshold)
        if box is None:
            raise RenderError(f"Page {page} is blank")
        pad = 2
        x0, y0 = max(0, box[0] - pad), max(0, box[1] - pad)
        x1, y1 = min(w, box[2] + pad), min(h, box[3] + pad)
        sx, sy = pw / w, ph / h
        bx, by, bw, bh = x0 * sx, y0 * sy, (x1 - x0) * sx, (y1 - y0) * sy

    LW, LH = spec.width_dots, spec.height_dots
    m = spec.margin_dots
    avail_w, avail_h = max(1, LW - 2 * m), max(1, LH - 2 * m)
    rotate = spec.rotate and (bw > bh) != (avail_w > avail_h)
    cw, ch = (bh, bw) if rotate else (bw, bh)
    scale = min(avail_w / cw, avail_h / ch)  # dots per point
    dpi = scale * 72
    crop = (round(bx * scale), round(by * scale), round(bw * scale), round(bh * scale))
    w, h, px = _render_gray(pdf_path, page, dpi, crop)
    if rotate:
        w, h, px = _rotate_cw(w, h, px)
    src_w = w
    w, h = min(w, LW), min(h, LH)

    # Threshold to ASCII '0' (black) / '1' (white) so int(..., 2) can pack bits in C.
    table = bytes((48 if v < spec.threshold else 49) for v in range(256))
    row_bytes = (LW + 7) // 8
    pad_bits = row_bytes * 8 - LW
    off_x, off_y = (LW - w) // 2, (LH - h) // 2
    blank = b"\xff" * row_bytes
    rows: list[bytes] = []
    for y in range(LH):
        sy = y - off_y
        if sy < 0 or sy >= h:
            rows.append(blank)
            continue
        line = px[sy * src_w: sy * src_w + w].translate(table)
        bits = b"1" * off_x + line + b"1" * (LW - off_x - w + pad_bits)
        rows.append(int(bits, 2).to_bytes(row_bytes, "big"))
    return Bitmap(LW, LH, rows)


def render_pdf(pdf_path: str, spec: LabelSpec, max_pages: int = 50) -> list[Bitmap]:
    sizes = page_sizes(pdf_path)
    if len(sizes) > max_pages:
        raise RenderError(f"PDF has {len(sizes)} pages; the limit is {max_pages}")
    return [render_page(pdf_path, i + 1, s, spec) for i, s in enumerate(sizes)]
