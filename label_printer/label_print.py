# Copyright (c) 2024, Your Company
# License: MIT

"""
label_print.py — Core backend for Label Printer app.

Provides whitelisted API endpoints called from the browser,
builds TSPL commands for 60x40mm labels, and sends them
to the Flask print agent running on the Raspberry Pi.

Compatible with ERPNext v15 and v16 / Frappe v15 and v16.
"""

import json
import re

import frappe
import requests
from frappe import _


# ─────────────────────────────────────────────────────────────
# Settings helper
# ─────────────────────────────────────────────────────────────


def get_printer_settings():
    """Fetch the Label Printer Settings single DocType."""
    return frappe.get_single("Label Printer Settings")


# ─────────────────────────────────────────────────────────────
# Whitelisted API — called from browser via frappe.call()
# ─────────────────────────────────────────────────────────────


@frappe.whitelist()
def test_connection():
    """
    Ping the print agent health endpoint and check API Key validity.
    Called by the 'Test Connection' button in Label Printer Settings.
    """
    settings = get_printer_settings()
    if not settings.agent_ip:
        frappe.throw(_("Please set the Print Agent IP first."))

    # 1. Verify basic network connection
    url_health = f"http://{settings.agent_ip}:{settings.agent_port}/health"
    try:
        resp = requests.get(url_health, timeout=5)
        resp.raise_for_status()
        health_data = resp.json()
    except requests.exceptions.ConnectionError:
        frappe.throw(
            _("Cannot connect to Print Agent at {0}:{1}. Is the agent running?").format(
                settings.agent_ip, settings.agent_port
            )
        )
    except requests.exceptions.Timeout:
        frappe.throw(_("Connection timed out. Check the IP address and network."))
    except Exception as e:
        frappe.throw(_("Error: {0}").format(str(e)))

    # 2. Verify API Key
    url_auth = f"http://{settings.agent_ip}:{settings.agent_port}/printers"
    headers = {"X-API-Key": settings.get_password("api_key")}
    try:
        resp = requests.get(url_auth, headers=headers, timeout=5)
        resp.raise_for_status()
    except requests.exceptions.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 401:
            frappe.throw(_("Connection OK, but API Key is Invalid! Update it in settings."))
        frappe.throw(_("Auth test returned an error: {0}").format(str(exc)))
    except Exception as e:
        frappe.throw(_("Auth test failed: {0}").format(str(e)))

    return health_data


@frappe.whitelist()
def get_printers():
    """
    Fetch the list of connected USB printer device paths from the print agent.
    Called before opening the Print Dialog in Delivery Note.
    """
    settings = get_printer_settings()
    if not settings.agent_ip:
        return []

    url = f"http://{settings.agent_ip}:{settings.agent_port}/printers"
    headers = {"X-API-Key": settings.get_password("api_key")}
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        return data.get("printers", [])
    except Exception:
        # Fallback to empty if agent is offline or errors
        return []


@frappe.whitelist()
def print_item_labels(docname, items_json, printer_device=None):
    """
    Send structured label data to the Pi print agent's /render_print endpoint.
    The Pi renders a bitmap label using DejaVu Sans font for clean, professional output.

    Args:
        docname        (str): Delivery Note name, e.g. "DN-2026-00042"
        items_json     (str): JSON array of dicts:
                              [{item_code, item_name, description, qty, uom}, ...]
        printer_device (str): Optional target printer path, e.g. "/dev/usb/lp1"
    """
    # ── Validate the Delivery Note ──────────────────────────
    dn = frappe.get_doc("Delivery Note", docname)
    if dn.docstatus != 1:
        frappe.throw(_("Delivery Note must be Submitted before printing labels."))

    # ── Parse items from browser ────────────────────────────
    items = json.loads(items_json)
    if not items:
        frappe.throw(_("No items selected for printing."))

    settings = get_printer_settings()
    company  = dn.company
    total_labels = 0

    # ── Send each item to the Pi render endpoint ─────────────
    for item in items:
        dn_qty = max(1, int(float(item.get("dn_qty", 1))))
        print_qty = max(1, int(float(item.get("print_qty", 1))))

        payload = {
            "company":          company,
            "item_code":        item.get("item_code",   ""),
            "item_name":        item.get("item_name",   ""),
            "description":      _strip_html(item.get("description", "")),
            "qty":              dn_qty,
            "uom":              item.get("uom",         ""),
            "copies":           print_qty,
            "label_width_mm":   int(settings.label_width),
            "label_height_mm":  int(settings.label_height),
            "gap_mm":           int(settings.gap_mm),
        }
        if printer_device:
            payload["device"] = printer_device

        send_render_request(payload, settings)
        total_labels += print_qty

    if not total_labels:
        frappe.throw(_("No valid items to print."))

    return _("✅ Sent {0} label(s) to printer successfully.").format(total_labels)


# ─────────────────────────────────────────────────────────────
# TSPL builder — 60 × 40 mm label
# ─────────────────────────────────────────────────────────────
#
# Label layout at 203 dpi  (60mm = 480 dots, 40mm = 320 dots):
#
#  Y=  8   Company Name                   (font 3, 1×1)
#  Y= 40   ─── divider bar ───────────────
#  Y= 48   Item Name                      (font 3, 1×1)  | QR Code
#  Y= 82   Description (truncated)        (font 2, 1×1)  | X=340
#  Y=110   Qty: N  UOM                    (font 2, 1×1)  |
#  Y=250   ─── divider bar ───────────────
#  Y=258   Item Code                      (font 2, 1×1)
#
# ─────────────────────────────────────────────────────────────


def _strip_html(text: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    if not text:
        return ""
    clean = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", clean).strip()


def _trunc(text: str, max_len: int) -> str:
    """Truncate text and escape TSPL double-quote characters."""
    text = str(text or "")[:max_len]
    # TSPL uses double-quoted strings; escape any embedded quotes
    return text.replace('"', "'")


def build_tspl(
    company: str,
    item_code: str,
    item_name: str,
    description: str,
    qty: int,
    uom: str,
    settings,
) -> str:
    """
    Return a complete TSPL command string for one item label.

    Layout (60mm × 40mm = 480 × 320 dots at 203 DPI):
    ┌─────────────────────────────────────────────────────┐
    │ [U] PT. UNITEK MAS INDONESIA                        │ ← Header
    ├─────────────────────────────────────────────────────┤
    │ ITEM DESC:                                          │ ← Body
    │ Double Splice Tape 8mm Yello                        │
    │ QTY: 1   UNIT: pcs                                  │
    ├─────────────────────────────────────────────────────┤
    │ www.unitekmasindonesia.com          ┌─────────────┐ │ ← Footer
    │ info@unitekmasindonesia.com         │  QR CODE    │ │
    │                                     └─────────────┘ │
    └─────────────────────────────────────────────────────┘
    """
    w = int(settings.label_width)    # mm, e.g. 60
    h = int(settings.label_height)   # mm, e.g. 40
    gap = int(settings.gap_mm)       # mm, e.g. 3

    # Text content — full width available now (no right-side QR in body)
    company_text = _trunc(company, 28)
    item_name_text = _trunc(item_name, 27)   # Font 3 (16 dots/char × 27 = 432 dots)
    desc_text = _trunc(_strip_html(description), 37)  # Font 2 (12 dots/char × 37 = 444)
    qty_uom_line = f"QTY: {qty}    UNIT: {_trunc(uom, 10)}"

    # Footer contact info (Font 1 = 8 dots/char wide)
    web_text = "www.unitekmasindonesia.com"
    email_text = "info@unitekmasindonesia.com"

    # QR code: cell_width=3 → ~87×87 dots; positioned bottom-right
    qr_x = 380   # 480 - 87 - 13 margin = 380
    qr_y = 220   # starts at Y=220, ends at Y=307 (within 320)

    lines = [
        f"SIZE {w} mm, {h} mm",
        f"GAP {gap} mm, 0",
        "DIRECTION 0",
        "CLS",
        # ── Header: Logo Box + Company Name ───────────────
        "BOX 20,5,50,35,2",
        'TEXT 28,8,"3",0,1,1,"U"',
        f'TEXT 60,8,"3",0,1,1,"{company_text}"',
        # ── Horizontal Divider 1 ───────────────────────────
        "BAR 20,42,440,2",
        # ── Body: ITEM DESC label ──────────────────────────
        'TEXT 20,48,"2",0,1,1,"ITEM DESC:"',
        # ── Body: Item name (full width, large font) ───────
        f'TEXT 20,68,"3",0,1,1,"{item_name_text}"',
    ]

    # Optional description line below item name
    if desc_text and desc_text != item_name_text:
        lines.append(f'TEXT 20,96,"2",0,1,1,"{desc_text}"')
        lines.append(f'TEXT 20,120,"2",0,1,1,"{qty_uom_line}"')
        div_y = 145
    else:
        lines.append(f'TEXT 20,96,"2",0,1,1,"{qty_uom_line}"')
        div_y = 122

    # ── Horizontal Divider 2 ───────────────────────────────
    lines.append(f"BAR 20,{div_y},440,2")

    footer_y = div_y + 8
    # ── Footer Left: Contact Info (Font 1 = smallest) ──────
    lines.append(f'TEXT 20,{footer_y},"1",0,1,1,"{web_text}"')
    lines.append(f'TEXT 20,{footer_y + 16},"1",0,1,1,"{email_text}"')

    # ── Footer Right: Small QR Code ────────────────────────
    lines.append(f'QRCODE {qr_x},{qr_y},M,3,A,0,"{item_code}"')

    # ── Print command ──────────────────────────────────────
    lines.append(f"PRINT {qty},1")

    return "\r\n".join(lines) + "\r\n"


# ─────────────────────────────────────────────────────────────
# HTTP transport — ERPNext → Raspberry Pi (bitmap render mode)
# ─────────────────────────────────────────────────────────────


def send_render_request(payload: dict, settings) -> None:
    """
    POST structured label data to the Pi agent's /render_print endpoint.
    The Pi renders the label as a bitmap using DejaVu Sans font and sends
    it to the printer via TSPL BITMAP command.
    Raises a Frappe exception with a user-friendly message on any error.
    """
    url = f"http://{settings.agent_ip}:{settings.agent_port}/render_print"
    headers = {"X-API-Key": settings.get_password("api_key")}

    try:
        resp = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=20,   # Rendering takes a little longer than raw TSPL
        )
        resp.raise_for_status()
    except requests.exceptions.ConnectionError:
        frappe.throw(
            _(
                "Cannot connect to Print Agent at {0}:{1}.<br>"
                "Please check: Is the Raspberry Pi online? Is the print agent running?"
            ).format(settings.agent_ip, settings.agent_port)
        )
    except requests.exceptions.Timeout:
        frappe.throw(
            _("Print Agent did not respond in time. Check the network or restart the agent.")
        )
    except requests.exceptions.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 401:
            frappe.throw(_("Invalid API Key. Update it in Label Printer Settings."))
        detail = ""
        try:
            detail = exc.response.json().get("error", "")
        except Exception:
            pass
        frappe.throw(_("Print Agent returned an error: {0} {1}").format(str(exc), detail))
    except Exception as exc:
        frappe.throw(_("Unexpected error while printing: {0}").format(str(exc)))
