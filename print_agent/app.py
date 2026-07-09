#!/usr/bin/env python3
"""
app.py — TSC TDP-225 Print Agent for Raspberry Pi
Receives label data from ERPNext, renders it as a bitmap using
DejaVu Sans font (Arial-like), and writes raw TSPL BITMAP bytes
to the USB printer for clean, professional label output.

Usage:
    python3 app.py

Environment variables:
    PRINT_AGENT_KEY   Shared secret API key (required, change from default!)
    PRINTER_DEVICE    USB device path (default: /dev/usb/lp0)
    PORT              HTTP port (default: 5000)
"""

import logging
import os

from flask import Flask, jsonify, request

# ─────────────────────────────────────────────────────────────
# Configuration — set via environment variables or edit defaults
# ─────────────────────────────────────────────────────────────

API_KEY        = os.environ.get("PRINT_AGENT_KEY", "change-this-to-a-strong-secret")
PRINTER_DEVICE = os.environ.get("PRINTER_DEVICE", "/dev/usb/lp0")
PORT           = int(os.environ.get("PORT", "5000"))

# Font paths (DejaVu Sans — free, Arial-like, pre-installed on Raspberry Pi OS)
FONT_BOLD    = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

# Fixed footer contact info
LABEL_WEB   = "www.unitekmasindonesia.com"
LABEL_EMAIL = "info@unitekmasindonesia.com"

# ─────────────────────────────────────────────────────────────
# Flask app
# ─────────────────────────────────────────────────────────────

app = Flask(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("print-agent")


def _auth_check():
    """Return None if auth passes, else a (response, status) tuple."""
    key = request.headers.get("X-API-Key", "")
    if key != API_KEY:
        log.warning("Unauthorized request from %s", request.remote_addr)
        return jsonify({"error": "Unauthorized"}), 401
    return None


def _load_font(path, size):
    """Load a TTF font with graceful fallback to PIL default."""
    from PIL import ImageFont
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        log.warning("Font not found: %s. Using default.", path)
        return ImageFont.load_default()


# ─────────────────────────────────────────────────────────────
# Bitmap label renderer
# ─────────────────────────────────────────────────────────────

def render_label_image(data: dict):
    """
    Render a label as a PIL RGB Image using DejaVu Sans font.

    Layout (60 × 40 mm = 480 × 320 dots at 203 DPI):
    ┌────────────────────────────────────────────────┐
    │ [U]  PT. UNITEK MAS INDONESIA                  │ ← Header
    ├────────────────────────────────────────────────┤
    │ ITEM DESC:                                     │ ← Body
    │ Double Splice Tape 8mm Yello                   │
    │ QTY: 1    UNIT: pcs                            │
    ├────────────────────────────────────────────────┤
    │ www.unitekmasindonesia.com       ┌──────────┐  │ ← Footer
    │ info@unitekmasindonesia.com      │ QR CODE  │  │
    │                                  └──────────┘  │
    └────────────────────────────────────────────────┘
    """
    from PIL import Image, ImageDraw
    import qrcode as _qr

    DPI   = 203
    w_mm  = int(data.get("label_width_mm", 60))
    h_mm  = int(data.get("label_height_mm", 40))
    W     = round(w_mm  / 25.4 * DPI)   # 480 dots
    H     = round(h_mm  / 25.4 * DPI)   # 320 dots
    
    # 0.5mm left/right = 4 dots, 2mm top/bottom = 16 dots at 203 DPI
    M_LR  = 4
    M_TB  = 16

    # Truncate text to fit the new wider printable area (472 dots wide)
    company     = str(data.get("company",     ""))[:34]
    item_name   = str(data.get("item_name",   ""))[:30]
    item_code   = str(data.get("item_code",   ""))
    description = str(data.get("description", ""))
    qty         = int(data.get("qty",  1))
    uom         = str(data.get("uom",  ""))[:12]

    # Load fonts (adjusted sizes for margin safety)
    f_hdr  = _load_font(FONT_BOLD,    22)   # Header company name
    f_logo = _load_font(FONT_BOLD,    22)   # Logo "U"
    f_lbl  = _load_font(FONT_REGULAR, 14)   # "ITEM DESC:" label
    f_name = _load_font(FONT_BOLD,    24)   # Item name
    f_qty  = _load_font(FONT_BOLD,    19)   # QTY: 10  UNIT: pcs
    f_foot = _load_font(FONT_REGULAR, 13)   # Footer contact text

    # Canvas — white background
    img  = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(img)

    # ── Header ───────────────────────────────────────────────
    # Logo box
    draw.rectangle([M_LR, M_TB, M_LR + 34, M_TB + 32], outline="black", width=2)
    draw.text((M_LR + 8, M_TB + 4), "U", font=f_logo, fill="black")
    # Company name
    draw.text((M_LR + 44, M_TB + 5), company, font=f_hdr, fill="black")
    # Divider 1
    draw.line([(M_LR, M_TB + 38), (W - M_LR, M_TB + 38)], fill="black", width=2)

    # ── Body ─────────────────────────────────────────────────
    # Keep text padded 16 dots from left for neatness
    text_pad = M_LR + 12
    draw.text((text_pad, M_TB + 48), "ITEM DESC:", font=f_lbl, fill="black")
    draw.text((text_pad, M_TB + 68), item_name,    font=f_name, fill="black")
    
    # Description (if different from name)
    if description and description != item_name:
        f_desc = _load_font(FONT_REGULAR, 18)
        draw.text((text_pad, M_TB + 102), description[:44], font=f_desc, fill="black")
        draw.text((text_pad, M_TB + 140), f"QTY: {qty}    UNIT: {uom}", font=f_qty, fill="black")
    else:
        draw.text((text_pad, M_TB + 120), f"QTY: {qty}    UNIT: {uom}", font=f_qty, fill="black")

    # Divider 2 (placed lower to separate footer, fits within H-M_TB = 304 dots)
    div_y = 200
    draw.line([(M_LR, div_y), (W - M_LR, div_y)], fill="black", width=2)

    # ── Footer Left: Contact Info ─────────────────────────────
    fy = div_y + 14
    draw.text((text_pad, fy),      LABEL_WEB,   font=f_foot, fill="black")
    draw.text((text_pad, fy + 22), LABEL_EMAIL, font=f_foot, fill="black")

    # ── Footer Right: QR Code ─────────────────────────────────
    qr = _qr.QRCode(
        version=None,
        error_correction=_qr.constants.ERROR_CORRECT_M,
        box_size=3,
        border=1,
    )
    qr.add_data(item_code)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    qr_w, qr_h = qr_img.size

    # Fit QR into footer area (div_y to H-M_TB is 200 to 304 = 104px tall)
    footer_h = H - M_TB - div_y - 6
    if qr_h > footer_h:
        scale  = footer_h / qr_h
        qr_img = qr_img.resize((int(qr_w * scale), footer_h))
        qr_w, qr_h = qr_img.size

    # Keep QR code 20 dots away from the right edge specifically, so it never gets cut off
    qr_x = W - qr_w - 20
    qr_y = div_y + (H - M_TB - div_y - qr_h) // 2
    img.paste(qr_img, (qr_x, qr_y))

    return img


def image_to_tspl_bytes(img, w_mm: int, h_mm: int, gap_mm: int, copies: int) -> bytes:
    """
    Convert a PIL Image to raw TSPL BITMAP bytes.
    Returns bytes ready to write to /dev/usb/lp*.

    TSPL BITMAP format: BITMAP x,y,width_bytes,height,mode,<binary data>
      - width_bytes = ceil(width_dots / 8)
      - mode 0 = overwrite
      - binary data: 1 bit per pixel, MSB = leftmost pixel, 1 = black
    """
    W = img.width
    H = img.height
    width_bytes = (W + 7) // 8   # 60 for 480-dot width

    # Convert to grayscale then threshold
    img_bw = img.convert("L")

    # Pack pixels into bits:
    # TSPL uses 0 for black (print dot) and 1 for white (no print dot) for this firmware.
    raw = bytearray()
    for y in range(H):
        for xb in range(width_bytes):
            byte_val = 0
            for bit in range(8):
                x = xb * 8 + bit
                is_black = False
                if x < W and img_bw.getpixel((x, y)) < 128:
                    is_black = True
                
                if not is_black:
                    # Set bit to 1 for white (no print)
                    byte_val |= (1 << (7 - bit))
            raw.append(byte_val)

    header = (
        f"SIZE {w_mm} mm, {h_mm} mm\r\n"
        f"GAP {gap_mm} mm, 0\r\n"
        f"DIRECTION 0\r\n"
        f"CLS\r\n"
        f"BITMAP 0,0,{width_bytes},{H},0,"
    ).encode("ascii")

    footer = f"\r\nPRINT {copies},1\r\n".encode("ascii")

    return bytes(header) + bytes(raw) + bytes(footer)


# ── Health endpoint ───────────────────────────────────────────


@app.route("/health", methods=["GET"])
def health():
    """
    Public endpoint — no auth required.
    Returns printer online/offline status.
    """
    online = os.path.exists(PRINTER_DEVICE)
    status = "online" if online else "offline"
    log.info("Health check — printer: %s (%s)", status, PRINTER_DEVICE)
    return jsonify({"status": "ok", "printer": status, "device": PRINTER_DEVICE})


# ── Get list of connected printers ───────────────────────────


@app.route("/printers", methods=["GET"])
def list_printers():
    """
    Authenticated endpoint.
    Returns a list of connected USB printer devices with names.
    """
    err = _auth_check()
    if err:
        return err

    import glob
    devices = sorted(glob.glob("/dev/usb/lp*"))
    printers = []

    for dev_path in devices:
        lp_name      = os.path.basename(dev_path)
        manufacturer = ""
        product      = ""
        sysfs_base   = f"/sys/class/usbmisc/{lp_name}/device/.."

        try:
            p = os.path.join(sysfs_base, "manufacturer")
            if os.path.exists(p):
                manufacturer = open(p).read().strip()
        except Exception:
            pass

        try:
            p = os.path.join(sysfs_base, "product")
            if os.path.exists(p):
                product = open(p).read().strip()
        except Exception:
            pass

        if manufacturer and product:
            label = f"{manufacturer} {product} ({dev_path})"
        elif manufacturer or product:
            label = f"{manufacturer or product} ({dev_path})"
        else:
            label = dev_path

        printers.append({"device": dev_path, "label": label,
                         "manufacturer": manufacturer, "product": product})

    log.info("Listed printers: %s", [p["label"] for p in printers])
    return jsonify({"status": "ok", "printers": printers})


# ── Raw TSPL print endpoint (legacy fallback) ─────────────────


@app.route("/print", methods=["POST"])
def print_label():
    """
    Authenticated endpoint — legacy raw TSPL mode.
    Expects JSON: { "tspl": "<TSPL commands>", "device": "/dev/usb/lp1" }
    """
    err = _auth_check()
    if err:
        return err

    data = request.get_json(silent=True)
    if not data or "tspl" not in data:
        return jsonify({"error": "Missing 'tspl' field in request body"}), 400

    tspl = data["tspl"]
    if not isinstance(tspl, str) or not tspl.strip():
        return jsonify({"error": "'tspl' must be a non-empty string"}), 400

    device = data.get("device", PRINTER_DEVICE)
    if not isinstance(device, str) or not device.startswith("/dev/usb/"):
        return jsonify({"error": "Invalid printer device path"}), 400

    if not os.path.exists(device):
        return jsonify({"error": f"Printer device not found: {device}"}), 503

    try:
        raw = tspl.encode("ascii", errors="replace")
        with open(device, "wb") as f:
            f.write(raw)
        log.info("(legacy) Printed %d bytes to %s from %s", len(raw), device, request.remote_addr)
        return jsonify({"status": "ok", "bytes_written": len(raw)})
    except PermissionError:
        return jsonify({"error": f"Permission denied: {device}", "hint": "Run setup.sh"}), 500
    except Exception as exc:
        log.error("Print error: %s", exc)
        return jsonify({"error": str(exc)}), 500


# ── Bitmap render + print endpoint ───────────────────────────


@app.route("/render_print", methods=["POST"])
def render_print():
    """
    Authenticated endpoint — bitmap rendering mode.
    Accepts structured JSON label data, renders a bitmap label
    using DejaVu Sans font, and writes raw TSPL BITMAP bytes
    to the USB printer for clean, professional output.

    Expected JSON fields:
        company          (str)  Company name
        item_code        (str)  Item code (also encoded in QR)
        item_name        (str)  Item display name
        description      (str)  Item description (optional)
        qty              (int)  Quantity
        uom              (str)  Unit of measure
        copies           (int)  Print copies (usually same as qty)
        device           (str)  Printer device path (optional)
        label_width_mm   (int)  Label width in mm (default 60)
        label_height_mm  (int)  Label height in mm (default 40)
        gap_mm           (int)  Gap between labels in mm (default 3)
    """
    err = _auth_check()
    if err:
        return err

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Missing JSON body"}), 400

    device = data.get("device", PRINTER_DEVICE)
    if not isinstance(device, str) or not device.startswith("/dev/usb/"):
        return jsonify({"error": "Invalid printer device path"}), 400

    if not os.path.exists(device):
        log.error("Printer device not found: %s", device)
        return jsonify({"error": f"Printer device not found: {device}",
                        "hint": "Is the USB cable connected?"}), 503

    w_mm   = int(data.get("label_width_mm",  60))
    h_mm   = int(data.get("label_height_mm", 40))
    gap_mm = int(data.get("gap_mm",           3))
    copies = max(1, int(data.get("copies",    1)))

    try:
        img = render_label_image(data)
        raw = image_to_tspl_bytes(img, w_mm, h_mm, gap_mm, copies)

        with open(device, "wb") as f:
            f.write(raw)

        log.info(
            "Rendered+printed label (%d bytes, %d copies) to %s from %s",
            len(raw), copies, device, request.remote_addr,
        )
        return jsonify({"status": "ok", "bytes_written": len(raw), "copies": copies})

    except ImportError as exc:
        log.error("Missing dependency: %s — run setup.sh", exc)
        return jsonify({"error": f"Missing dependency: {exc}. Run setup.sh to install."}), 500
    except Exception as exc:
        log.error("Render/print error: %s", exc, exc_info=True)
        return jsonify({"error": str(exc)}), 500


# ─────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("=" * 50)
    log.info("TSC TDP-225 Print Agent starting")
    log.info("  Default Device : %s", PRINTER_DEVICE)
    log.info("  Port           : %s", PORT)
    log.info("  API Key        : %s***", API_KEY[:4] if len(API_KEY) > 4 else "****")
    log.info("=" * 50)
    app.run(host="0.0.0.0", port=PORT)
