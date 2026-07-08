# Copyright (c) 2024, Your Company. License: MIT

import frappe
from frappe import _
from frappe.model.document import Document


class LabelPrinterSettings(Document):
    """
    Single DocType that stores all configuration for the
    label printer integration (Pi IP, port, key, label size).
    """

    def validate(self):
        if self.agent_port and not (1 <= int(self.agent_port) <= 65535):
            frappe.throw(_("Port must be between 1 and 65535."))

        if self.label_width and float(self.label_width) <= 0:
            frappe.throw(_("Label width must be greater than 0."))

        if self.label_height and float(self.label_height) <= 0:
            frappe.throw(_("Label height must be greater than 0."))
