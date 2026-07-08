// Copyright (c) 2024, Your Company. License: MIT
// label_printer_settings.js — Wires up the "Test Connection" button
// in Label Printer Settings form.

frappe.ui.form.on("Label Printer Settings", {
    refresh(frm) {
        // Attach handler for the Test Connection button field
        frm.fields_dict["test_connection_btn"] &&
            frm.fields_dict["test_connection_btn"].$input &&
            frm.fields_dict["test_connection_btn"].$input.on("click", () =>
                test_conn(frm)
            );
    },

    // Also handle via the standard button click event
    test_connection_btn(frm) {
        test_conn(frm);
    },
});

function test_conn(frm) {
    if (!frm.doc.agent_ip) {
        frappe.msgprint(__("Please enter the Print Agent IP first."));
        return;
    }

    frappe.show_alert(
        { message: __("Testing connection…"), indicator: "blue" },
        3
    );

    frappe.call({
        method: "label_printer.label_print.test_connection",
        callback(r) {
            if (r.message) {
                const printer = r.message.printer || "unknown";
                const indicator = printer === "online" ? "green" : "orange";
                const icon = printer === "online" ? "✅" : "⚠️";
                frappe.show_alert(
                    {
                        message: `${icon} ${__("Agent reachable. Printer")}: <b>${printer}</b>`,
                        indicator: indicator,
                    },
                    6
                );
            }
        },
        error() {
            frappe.show_alert(
                {
                    message: __("❌ Cannot reach the Print Agent. Check IP, port, and network."),
                    indicator: "red",
                },
                8
            );
        },
    });
}
