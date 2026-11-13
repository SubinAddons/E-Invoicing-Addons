"""Approved provider identity projected onto the accounting invoice."""
import frappe

UUID_FIELD = "custom_addons_einv_uuid"


def latest_submission(sales_invoice, doctype="Sales Invoice"):
    from addons_einvoicing.sources import source_field
    rows = frappe.get_all("Addons E Invoice Submission",
        filters={source_field(doctype): sales_invoice},
        fields=["name", "status", "provider_uuid", "provider"],
        order_by="creation desc, name desc", limit_page_length=1)
    return rows[0] if rows else None


def sync_invoice_uuid(sales_invoice, doctype="Sales Invoice"):
    row = latest_submission(sales_invoice, doctype)
    value = row.provider_uuid if row and row.status == "Approved" else ""
    frappe.db.set_value(doctype, sales_invoice, UUID_FIELD, value or "", update_modified=False)


def backfill():
    from addons_einvoicing.sources import source_field
    for doctype in ("Sales Invoice", "Purchase Invoice"):
        field = source_field(doctype)
        for row in frappe.get_all("Addons E Invoice Submission", fields=[field], group_by=field, limit_page_length=0):
            if row.get(field):
                sync_invoice_uuid(row[field], doctype)
