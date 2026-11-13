import frappe
from addons_einvoicing.service import build, connection_for, internal_save, prepare


def before_submit(doc, method=None):
    if not doc.get("custom_addons_einv_enabled"):
        return
    connection = connection_for(doc.company)
    build(doc, connection)


def on_submit(doc, method=None):
    if not doc.get("custom_addons_einv_enabled"):
        return
    connection = connection_for(doc.company)
    if connection.get("auto_submit_purchase" if doc.doctype == "Purchase Invoice" else "auto_submit"):
        prepare(doc, connection)


def before_cancel(doc, method=None):
    from addons_einvoicing.sources import source_field
    field = source_field(doc.doctype)
    frappe.db.sql(f"select name from `tab{doc.doctype}` where name=%s for update", doc.name)
    for row in frappe.get_all("Addons E Invoice Submission", filters={field: doc.name}, fields=["name", "attempts", "provider_uuid"]):
        if row.attempts or row.provider_uuid:
            frappe.throw("This invoice has an Ardentax submission attempt. Resolve its external state and issue a credit note instead of cancelling it.")
        submission = frappe.get_doc("Addons E Invoice Submission", row.name)
        submission.status = "Stopped"
        internal_save(submission)
