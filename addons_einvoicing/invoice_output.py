"""Approved provider identity projected onto the accounting invoice."""
import frappe

UUID_FIELD = "custom_addons_einv_uuid"


def latest_submission(sales_invoice):
    rows = frappe.get_all("Addons E Invoice Submission",
        filters={"sales_invoice": sales_invoice},
        fields=["name", "status", "provider_uuid", "provider"],
        order_by="creation desc, name desc", limit_page_length=1)
    return rows[0] if rows else None


def sync_invoice_uuid(sales_invoice):
    row = latest_submission(sales_invoice)
    value = row.provider_uuid if row and row.status == "Approved" else ""
    frappe.db.set_value("Sales Invoice", sales_invoice, UUID_FIELD, value or "", update_modified=False)


def backfill():
    for row in frappe.get_all("Addons E Invoice Submission", fields=["sales_invoice"], group_by="sales_invoice", limit_page_length=0):
        if row.sales_invoice:
            sync_invoice_uuid(row.sales_invoice)
