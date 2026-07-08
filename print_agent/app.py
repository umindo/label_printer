#!/usr/bin/env python3
"""
app.py — TSC TDP-225 Print Agent for Raspberry Pi
Receives TSPL commands from ERPNext and writes them to the USB printer.

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

API_KEY = os.environ.get("PRINT_AGENT_KEY", "change-this-to-a-strong-secret")
PRINTER_DEVICE = os.environ.get("PRINTER_DEVICE", "/dev/usb/lp0")
PORT = int(os.environ.get("PORT", "5000"))

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
    return jsonify(
        {
            "status": "ok",
            "printer": status,
            "device": PRINTER_DEVICE,
        }
    )


# ── Get list of connected printers ───────────────────────────


@app.route("/printers", methods=["GET"])
def list_printers():
    """
    Authenticated endpoint.
    Returns a list of connected USB printer device paths.
    """
    err = _auth_check()
    if err:
        return err

    import glob
    devices = glob.glob("/dev/usb/lp*")
    log.info("Listed printers: %s", devices)
    return jsonify({"status": "ok", "printers": devices})


# ── Print endpoint ────────────────────────────────────────────


@app.route("/print", methods=["POST"])
def print_label():
    """
    Authenticated endpoint.
    Expects JSON body:
    {
        "tspl": "<TSPL command string>",
        "device": "/dev/usb/lp1"  (optional)
    }
    Writes raw TSPL bytes directly to the USB printer device.
    """
    # Auth
    err = _auth_check()
    if err:
        return err

    # Parse body
    data = request.get_json(silent=True)
    if not data or "tspl" not in data:
        return jsonify({"error": "Missing 'tspl' field in request body"}), 400

    tspl = data["tspl"]
    if not isinstance(tspl, str) or not tspl.strip():
        return jsonify({"error": "'tspl' must be a non-empty string"}), 400

    # Read and validate custom target device
    device = data.get("device", PRINTER_DEVICE)
    if not isinstance(device, str) or not (device.startswith("/dev/usb/lp") or device.startswith("/dev/usb/")):
        return jsonify({"error": "Invalid printer device path. Must be under /dev/usb/"}), 400

    # Check device
    if not os.path.exists(device):
        log.error("Printer device not found: %s", device)
        return (
            jsonify(
                {
                    "error": f"Printer device not found: {device}",
                    "hint": "Is the USB cable connected? Run setup.sh to fix permissions.",
                }
            ),
            503,
        )

    # Write to printer
    try:
        raw = tspl.encode("ascii", errors="replace")
        with open(device, "wb") as printer:
            printer.write(raw)
        log.info(
            "Printed %d bytes to %s from %s",
            len(raw),
            device,
            request.remote_addr,
        )
        return jsonify({"status": "ok", "bytes_written": len(raw)})

    except PermissionError:
        log.error("Permission denied: %s", device)
        return (
            jsonify(
                {
                    "error": f"Permission denied: {device}",
                    "hint": "Run setup.sh or: sudo chmod 666 /dev/usb/lp*",
                }
            ),
            500,
        )
    except OSError as exc:
        log.error("OS error writing to printer: %s", exc)
        return jsonify({"error": str(exc)}), 500
    except Exception as exc:
        log.error("Unexpected error: %s", exc)
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
