from urllib.parse import quote

import frappe
from frappe.model.document import Document
from frappe.utils import get_url

from addons_einvoicing.client import validate_base_url


class ProtectedRecord(Document):
    def validate(self):
        if not frappe.flags.get("addons_einv_internal"):
            frappe.throw("Integration records can only be changed through the app actions", frappe.PermissionError)

    def on_trash(self):
        frappe.throw("Integration audit records must be retained", frappe.PermissionError)


class Connection(Document):
    def validate(self):
        if self.provider == "Fynamics":
            from addons_einvoicing.fynamics import validate_base_url as validate_fynamics
            self.api_base_url = validate_fynamics(self.api_base_url, self.environment)
            from addons_einvoicing.fynamics_service import supplier_party
            supplier_party(self)
        elif self.provider == "ArdentaxIT":
            self.api_base_url = validate_base_url(self.api_base_url, self.environment)
            if self.api_version != "20260507" or not self.org_id or not self.business_profile_id:
                frappe.throw("ArdentaxIT requires API version 20260507, organization and business profile")
        else:
            frappe.throw("Unsupported API provider")
        if self.enabled and self.environment == "Production" and not self.production_verified:
            frappe.throw("Complete sandbox acceptance before enabling production")
        old = self.get_doc_before_save()
        if old and (frappe.db.exists("Addons E Invoice Submission", {"connection": self.name}) or frappe.db.exists("Addons E Invoice Webhook Event", {"connection": self.name})): 
            for key in ("provider", "company", "environment", "api_base_url", "org_id", "business_profile_id", "api_version", "client_id", "supplier_address", "supplier_endpoint", "supplier_scheme", "supplier_registration", "supplier_registration_scheme", "supplier_authority"):
                if old.get(key) != self.get(key):
                    frappe.throw(f"{key} cannot change after a submission exists. Use a separate production site/connection; never repoint historical submissions.")
        for table, key in ((self.uom_mappings, "uom"), (self.tax_mappings, "item_tax_template")):
            values = [row.get(key) or "" for row in table]
            if len(set(values)) != len(values):
                frappe.throw(f"Duplicate {key} mapping")
        for row in self.tax_mappings:
            if row.item_tax_template:
                company = frappe.db.get_value("Item Tax Template", row.item_tax_template, "company")
                if company and company != self.company:
                    frappe.throw("Item Tax Template must belong to this company")
        self.webhook_url = get_url() + "/api/method/addons_einvoicing.api.webhook?connection=" + quote(self.name or self.company, safe="")

    def on_trash(self):
        if frappe.db.exists("Addons E Invoice Submission", {"connection": self.name}) or frappe.db.exists("Addons E Invoice Webhook Event", {"connection": self.name}):
            frappe.throw("Disable connections with history; do not delete them")
