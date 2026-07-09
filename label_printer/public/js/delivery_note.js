// Copyright (c) 2024, Your Company. License: MIT
// delivery_note.js — Adds "Print Item Labels" button to submitted Delivery Note.
// Compatible with Frappe v15 and v16 (uses stable frappe.ui.form API).

frappe.ui.form.on("Delivery Note", {
    refresh(frm) {
        // Only show button on submitted documents
        if (frm.doc.docstatus !== 1) return;

        frm.add_custom_button(
            __("Print Item Labels"),
            () => show_print_dialog(frm),
            __("🖨️ Labels")
        );
    },
});

// ─────────────────────────────────────────────────────────────
// Dialog
// ─────────────────────────────────────────────────────────────

function show_print_dialog(frm) {
    const items = frm.doc.items || [];
    if (!items.length) {
        frappe.msgprint(__("No items found in this Delivery Note."));
        return;
    }

    frappe.call({
        method: "label_printer.label_print.get_printers",
        callback(r) {
            let printers = r.message || [];

            // Normalize: API may return objects {device, label} or plain strings
            if (printers.length > 0 && typeof printers[0] === "object") {
                // Already objects with label + device
            } else {
                // Fallback: convert plain strings to objects
                printers = printers.map(p => ({ device: p, label: p }));
            }

            if (!printers.length) {
                printers = [
                    { device: "/dev/usb/lp0", label: "/dev/usb/lp0" },
                    { device: "/dev/usb/lp1", label: "/dev/usb/lp1" },
                ];
            }

            open_print_dialog(frm, items, printers);
        }
    });
}

function open_print_dialog(frm, items, printers) {
    // Build "label\ndevice_path" options for Select field
    // The Select value will be the label, we map it back to device on submit
    const option_labels = printers.map(p => p.label);

    const dialog = new frappe.ui.Dialog({
        title: __("🖨️ Print Item Labels"),
        size: "large",
        fields: [
            {
                label: __("Select Printer"),
                fieldname: "printer_label",
                fieldtype: "Select",
                options: option_labels,
                default: option_labels[0],
            },
            {
                fieldtype: "Section Break"
            },
            {
                fieldtype: "HTML",
                fieldname: "items_html",
                options: build_items_html(items),
            },
        ],
        primary_action_label: __("Print Labels"),
        primary_action() {
            const selected = get_selected_items(dialog, items);
            if (!selected.length) {
                frappe.msgprint(__("Please select at least one item."));
                return;
            }
            // Map selected label back to device path
            const chosen_label = dialog.get_value("printer_label");
            const printer = printers.find(p => p.label === chosen_label);
            const printer_device = printer ? printer.device : chosen_label;

            dialog.hide();
            send_print_request(frm.doc.name, selected, printer_device);
        },
    });

    dialog.show();

    // Wire up interactivity after DOM renders
    setTimeout(() => init_interactions(dialog, items), 150);
}

// ──────�            const dn_qty = Math.max(1, Math.round(item.qty || 1));
            return `
            <tr>
                <td style="text-align:center;vertical-align:middle;width:40px">
                    <input type="checkbox" class="lp-item-check" data-idx="${idx}" checked>
                </td>
                <td style="vertical-align:middle">
                    <strong>${frappe.utils.escape_html(item.item_code || "")}</strong>
                </td>
                <td style="vertical-align:middle">
                    ${frappe.utils.escape_html(item.item_name || "")}
                </td>
                <td style="text-align:center;vertical-align:middle">
                    ${dn_qty} ${frappe.utils.escape_html(item.uom || "")}
                </td>
                <td style="text-align:center;width:90px">
                    <input type="number"
                           class="lp-qty-input form-control form-control-sm"
                           data-idx="${idx}"
                           value="1"
                           min="1"
                           style="width:75px;display:inline-block">
                </td>
            </tr>`;
        })
        .join("");

    return `
        <div style="margin-bottom:12px;display:flex;align-items:center;gap:16px">
            <label style="margin:0;cursor:pointer">
                <input type="checkbox" id="lp-check-all" checked>
                &nbsp;<strong>${__("Select All")}</strong>
            </label>
        </div>

        <table class="table table-bordered table-sm" style="margin-bottom:8px">
            <thead style="background:var(--subtle-accent,#f0f4f7)">
                <tr>
                    <th style="text-align:center"></th>
                    <th>${__("Item Code")}</th>
                    <th>${__("Item Name")}</th>
                    <th style="text-align:center">${__("DN Qty")}</th>
                    <th style="text-align:center">${__("Labels to Print")}</th>
                </tr>
            </thead>
            <tbody>${rows}</tbody>
        </table>

        <div style="font-size:14px;color:var(--text-muted,#888)">
            ℹ️ ${__("Total Labels")}:&nbsp;
            <strong id="lp-total-count" style="color:var(--text-color,#333)">—</strong>
        </div>`;
}

// ─────────────────────────────────────────────────────────────
// Interactions — checkbox toggle and total counter
// ─────────────────────────────────────────────────────────────

function init_interactions(dialog, items) {
    const $w = dialog.$wrapper;

    // Initial total
    update_total($w);

    // Select-all checkbox
    $w.find("#lp-check-all").on("change", function () {
        $w.find(".lp-item-check").prop("checked", this.checked);
        update_total($w);
    });

    // Per-row checkbox
    $w.find(".lp-item-check").on("change", function () {
        const allChecked =
            $w.find(".lp-item-check").length ===
            $w.find(".lp-item-check:checked").length;
        $w.find("#lp-check-all").prop("checked", allChecked);
        update_total($w);
    });

    // Qty input
    $w.find(".lp-qty-input").on("input change", function () {
        // Enforce minimum of 1
        if (parseInt(this.value) < 1 || isNaN(parseInt(this.value))) {
            this.value = 1;
        }
        update_total($w);
    });
}

function update_total($w) {
    let total = 0;
    $w.find(".lp-item-check:checked").each(function () {
        const idx = $(this).data("idx");
        const qty =
            parseInt($w.find(`.lp-qty-input[data-idx="${idx}"]`).val()) || 0;
        total += qty;
    });
    $w.find("#lp-total-count").text(total);
}

// ─────────────────────────────────────────────────────────────
// Collect selected items from dialog
// ─────────────────────────────────────────────────────────────

function get_selected_items(dialog, items) {
    const $w = dialog.$wrapper;
    const selected = [];

    $w.find(".lp-item-check:checked").each(function () {
        const idx = $(this).data("idx");
        const item = items[idx];
        const print_qty =
            parseInt($w.find(`.lp-qty-input[data-idx="${idx}"]`).val()) || 1;

        selected.push({
            item_code: item.item_code || "",
            item_name: item.item_name || "",
            description: item.description || "",
            dn_qty: Math.max(1, Math.round(item.qty || 1)),
            print_qty: print_qty,
            uom: item.uom || "",
        });
    });

    return selected;
}───────────────────────────────────────────────────────────
// Collect selected items from dialog
// ─────────────────────────────────────────────────────────────

function get_selected_items(dialog, items) {
    const $w = dialog.$wrapper;
    const selected = [];

    $w.find(".lp-item-check:checked").each(function () {
        const idx = $(this).data("idx");
        const item = items[idx];
        const qty =
            parseInt($w.find(`.lp-qty-input[data-idx="${idx}"]`).val()) || 1;

        selected.push({
            item_code: item.item_code || "",
            item_name: item.item_name || "",
            description: item.description || "",
            qty: qty,
            uom: item.uom || "",
        });
    });

    return selected;
}

// ─────────────────────────────────────────────────────────────
// API call — ERPNext → label_print.py → Raspberry Pi
// ─────────────────────────────────────────────────────────────

function send_print_request(docname, selected_items, printer_device) {
    frappe.show_alert(
        { message: __("Sending to printer…"), indicator: "blue" },
        3
    );

    frappe.call({
        method: "label_printer.label_print.print_item_labels",
        args: {
            docname: docname,
            items_json: JSON.stringify(selected_items),
            printer_device: printer_device,
        },
        callback(r) {
            if (r.message) {
                frappe.show_alert(
                    { message: r.message, indicator: "green" },
                    6
                );
            }
        },
        error() {
            // Frappe already shows the server-side exception toast;
            // show an extra hint for the user.
            frappe.show_alert(
                {
                    message: __(
                        "Print failed. Check <b>Label Printer Settings</b> and confirm the Raspberry Pi agent is running."
                    ),
                    indicator: "red",
                },
                8
            );
        },
    });
}
