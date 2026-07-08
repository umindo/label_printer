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
    Build TSPL commands for each selected item and send to the print agent.

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
    company = dn.company

    # ── Build TSPL for every selected item ──────────────────
    tspl_blocks = []
    total_labels = 0

    for item in items:
        qty = max(1, int(float(item.get("qty", 1))))
        tspl = build_tspl(
            company=company,
            item_code=item.get("item_code", ""),
            item_name=item.get("item_name", ""),
            description=item.get("description", ""),
            qty=qty,
            uom=item.get("uom", ""),
            settings=settings,
        )
        tspl_blocks.append(tspl)
        total_labels += qty

    if not tspl_blocks:
        frappe.throw(_("No valid items to print."))

    # ── Send combined TSPL to Raspberry Pi agent ─────────────
    combined_tspl = "\r\n".join(tspl_blocks)
    send_to_print_agent(combined_tspl, settings, device=printer_device)

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
    The PRINT command is appended with the requested qty so the
    printer produces exactly qty copies in one job.
    """
    w = settings.label_width    # mm, e.g. 60
    h = settings.label_height   # mm, e.g. 40
    gap = settings.gap_mm       # mm, e.g. 3
    barcode_type = settings.barcode_type  # "QR Code" or "Code 128"

    company_text = _trunc(company, 30)
    item_name_text = _trunc(item_name, 28)
    desc_text = _trunc(_strip_html(description), 40)
    qty_line = f"Qty: {qty}  {_trunc(uom, 10)}"
    code_text = _trunc(item_code, 35)

    lines = [
        f"SIZE {w} mm, {h} mm",
        f"GAP {gap} mm, 0",
        "DIRECTION 0",
        "CLS",
        # ── Company name ────────────────────────────────────
        f'TEXT 5,8,"3",0,1,1,"{company_text}"',
        # ── Horizontal divider ──────────────────────────────
        "BAR 0,40,480,2",
        # ── Item name ───────────────────────────────────────
        f'TEXT 5,48,"3",0,1,1,"{item_name_text}"',
    ]

    # ── Description (omit if empty) ─────────────────────────
    if desc_text:
        lines.append(f'TEXT 5,82,"2",0,1,1,"{desc_text}"')

    # ── Qty + UOM ───────────────────────────────────────────
    lines.append(f'TEXT 5,110,"2",0,1,1,"{qty_line}"')

    # ── Bottom divider ──────────────────────────────────────
    lines.append("BAR 0,250,480,2")

    # ── Item code at bottom ─────────────────────────────────
    lines.append(f'TEXT 5,258,"2",0,1,1,"{code_text}"')

    # ── Barcode / QR Code on the right side ─────────────────
    if barcode_type == "QR Code":
        # QRCODE x, y, ECC, cell_width, mode, rotation, "data"
        # cell_width=5 → ~105 dots wide, fits right of 340..445
        lines.append(f'QRCODE 340,48,M,5,A,0,"{item_code}"')
    else:
        # Code 128 — placed below text content
        lines.append(f'BARCODE 5,155,"128",80,1,0,2,2,"{item_code}"')

    # ── Print qty copies ────────────────────────────────────
    lines.append(f"PRINT {qty},1")

    return "\r\n".join(lines)


# ─────────────────────────────────────────────────────────────
# HTTP transport — ERPNext → Raspberry Pi
# ─────────────────────────────────────────────────────────────


def send_to_print_agent(tspl_data: str, settings, device=None) -> None:
    """
    POST the combined TSPL string to the Flask print agent on the Pi.
    Raises a Frappe exception with a user-friendly message on any error.
    """
    url = f"http://{settings.agent_ip}:{settings.agent_port}/print"
    headers = {"X-API-Key": settings.get_password("api_key")}

    payload = {"tspl": tspl_data}
    if device:
        payload["device"] = device

    try:
        resp = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=10,
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
        frappe.throw(_("Print Agent returned an error: {0}").format(str(exc)))
    except Exception as exc:
        frappe.throw(_("Unexpected error while printing: {0}").format(str(exc)))
