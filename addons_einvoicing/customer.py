"""Validate opted-in customer records on UI, imports and API saves."""
import frappe

CORE_FIELDS = {
    "custom_addons_einv_legal_name": "E-Invoice Legal Name",
    "custom_addons_einv_email": "E-Invoice Email",
    "custom_addons_einv_endpoint_id": "Peppol Endpoint ID",
    "custom_addons_einv_endpoint_scheme": "Peppol Endpoint Scheme",
    "custom_addons_einv_registration_id": "Buyer Legal Registration ID",
    "custom_addons_einv_registration_type": "Buyer Registration Type",
}

def validate(doc, method=None):
    if not doc.get("custom_addons_einv_enabled"):
        return
    fields = dict(CORE_FIELDS)
    if doc.get("custom_addons_einv_endpoint_scheme") == "0235":
        fields["custom_addons_einv_tin"] = "UAE TIN"
    missing = [label for field, label in fields.items() if not str(doc.get(field) or "").strip()]
    if missing:
        frappe.throw("Complete the mandatory e-invoicing customer fields: " + ", ".join(missing))
