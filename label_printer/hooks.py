app_name = "label_printer"
app_title = "Label Printer"
app_publisher = "Your Company"
app_description = "Print TSPL item labels from Delivery Note via TSC TDP-225 on Raspberry Pi"
app_version = "1.0.0"
app_license = "MIT"
app_icon = "octicon octicon-tag"
app_color = "blue"

# ─────────────────────────────────────────────────────────────
# DocType JS — inject custom JS into Delivery Note and Settings
# Compatible with Frappe v15 and v16
# ─────────────────────────────────────────────────────────────
doctype_js = {
    "Delivery Note": "public/js/delivery_note.js",
    "Label Printer Settings": "public/js/label_printer_settings.js",
}
