import json

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def setup():
    if int(frappe.__version__.split(".")[0]) not in {15, 16}:
        frappe.throw("Addons - E invoicing supports Frappe 15 and 16")
    if not frappe.db.exists("Role", "Addons E Invoice Operator"):
        frappe.get_doc({"doctype": "Role", "role_name": "Addons E Invoice Operator", "desk_access": 1}).insert(ignore_permissions=True)
    def f(name, label, fieldtype="Data", **kw):
        return dict(fieldname="custom_addons_einv_" + name, label=label, fieldtype=fieldtype, **kw)
    required_customer = {"mandatory_depends_on": "eval:doc.custom_addons_einv_enabled"}
    create_custom_fields({
        "Customer": [
            f("section", "Addons - E invoicing", "Section Break", insert_after="customer_name"),
            f("enabled", "Enable E-Invoicing", "Check", default="0"),
            f("legal_name", "E-Invoice Legal Name", **required_customer), f("email", "E-Invoice Email", options="Email", **required_customer),
            f("telephone", "E-Invoice Telephone"),
            f("registration_id", "Buyer Legal Registration ID", **required_customer),
            f("registration_type", "Buyer Registration Type", **required_customer, description="Provider registration code, for example CD for Cabinet Decision or TL for Trade License."),
            f("registration_authority", "Buyer Registration Issuing Authority"),
            f("tin", "UAE TIN", mandatory_depends_on="eval:doc.custom_addons_einv_enabled && doc.custom_addons_einv_endpoint_scheme == '0235'"), f("endpoint_id", "Peppol Endpoint ID", **required_customer),
            f("endpoint_scheme", "Peppol Endpoint Scheme", default="0235", **required_customer),
        ],
        "Address": [f("region", "E-Invoice Region / Emirate Code", insert_after="state", description="UAE: DXB, AUH, SHJ, UAQ, FUJ, AJM or RAK. Other countries: appropriate region code.")],
        "Sales Invoice": [
            f("uuid", "E-Invoice UUID", read_only=1, no_copy=1, allow_on_submit=1, insert_after="custom_addons_einv_enabled", depends_on="eval:doc.custom_addons_einv_uuid", description="Provider UUID of the latest approved e-invoice."),
            f("section", "Addons - E invoicing", "Section Break", insert_after="customer"),
            f("enabled", "Enable E-Invoicing", "Check", default="0", allow_on_submit=1),
            f("type_code", "E-Invoice Type", "Select", options="380\n480", default="380"),
            f("profile_execution_id", "Transaction Profile", "Select", options="00000000\n00000001\n00000010\n00000011\n01000000", default="00000000", description="00000000 Standard; 00000001 Export; 00000010 E-commerce; 00000011 Export e-commerce; 01000000 Deemed Supply (Ardentax only). Select the actual transaction scenario.", allow_on_submit=1),
            f("payment_code", "Payment Means Code", allow_on_submit=1, description="Use ArdentaxIT payment code list, e.g. 30 for credit transfer."),
            f("supply_date", "Actual Supply Date", "Date", allow_on_submit=1),
            f("aed_rate", "AED per Invoice Currency Unit", "Float", precision="8"),
            f("discrepancy", "Credit Note Discrepancy Code", "Select", options="\nDL8.61.1.A\nDL8.61.1.B\nDL8.61.1.C\nDL8.61.1.D\nDL8.61.1.E\nVD", allow_on_submit=1),
        ],
    }, update=True)
    if not frappe.db.exists("Workspace", "Addons - E invoicing"):
        shortcuts = [{"label": title, "type": "DocType", "link_to": target} for title, target in [
            ("Company Settings", "Addons E Invoice Settings"), ("Submissions", "Addons E Invoice Submission"),
            ("Webhook Events", "Addons E Invoice Webhook Event"), ("Incoming Documents", "Addons E Invoice Inbox"),
            ("Audit Trail", "Addons E Invoice Audit")]]
        shortcuts.insert(0, {"label": "Dashboard", "type": "Page", "link_to": "addons-e-invoice-dashboard"})
        content = [{"id": "title", "type": "header", "data": {"text": "Addons - E invoicing", "col": 12}}]
        content += [{"id": f"link-{i}", "type": "shortcut", "data": {"shortcut_name": x["label"], "col": 4}} for i, x in enumerate(shortcuts)]
        frappe.get_doc({"doctype": "Workspace", "name": "Addons - E invoicing", "label": "Addons - E invoicing",
            "title": "Addons - E invoicing", "module": "Addons Einvoicing", "public": 1,
            "icon": "invoice", "content": json.dumps(content), "shortcuts": shortcuts,
            "roles": [{"role": "System Manager"}, {"role": "Addons E Invoice Operator"}]}).insert(ignore_permissions=True)

    from addons_einvoicing.invoice_output import backfill
    backfill()
