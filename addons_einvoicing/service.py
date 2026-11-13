import json

import frappe
from frappe.utils import get_system_timezone

from addons_einvoicing.client import Client
from addons_einvoicing.domain import MappingError, build_payload, canonical, digest


def internal_save(doc):
    previous = frappe.flags.get("addons_einv_internal")
    frappe.flags.addons_einv_internal = True
    try:
        if doc.is_new():
            doc.insert(ignore_permissions=True)
        else:
            doc.save(ignore_permissions=True)
    finally:
        frappe.flags.addons_einv_internal = previous
    return doc


def connection_for(company, active=True):
    name = frappe.db.get_value("Addons E Invoice Settings", {"company": company}, "name")
    if not name:
        frappe.throw("Configure an Addons E Invoice Settings for this company")
    doc = frappe.get_doc("Addons E Invoice Settings", name)
    if active and not doc.enabled:
        frappe.throw("E-invoice connection is disabled")
    if active and doc.environment == "Production" and not doc.production_verified:
        frappe.throw("Production requires completed sandbox verification on the connection")
    return doc


def client(connection):
    if connection.provider == "Fynamics":
        from addons_einvoicing.fynamics import Client as FynamicsClient
        return FynamicsClient(connection, frappe.cache)
    return Client(connection, frappe.cache)


def build(invoice, connection):
    if invoice.doctype == "Purchase Invoice":
        from addons_einvoicing.purchase import build as build_purchase
        return build_purchase(invoice, connection)
    customer = frappe.get_doc("Customer", invoice.customer).as_dict()
    if not invoice.customer_address:
        frappe.throw("A customer billing address is required")
    address = frappe.get_doc("Address", invoice.customer_address).as_dict()
    country = frappe.db.get_value("Country", address.country, "code") or ""
    data = invoice.as_dict()
    if invoice.shipping_address_name:
        shipping = frappe.get_doc("Address", invoice.shipping_address_name)
        region = shipping.get("custom_addons_einv_region")
        code = (frappe.db.get_value("Country", shipping.country, "code") or "").upper()
        if not all((shipping.address_line1, shipping.city, region, shipping.country, code)):
            frappe.throw("Complete street, city, region and country on the shipping address")
        data["_delivery_address"] = {"street_name": shipping.address_line1, "city_name": shipping.city,
            "country_subentity": region, "country": shipping.country, "country_code": code}
    original = frappe.get_doc("Sales Invoice", invoice.return_against).as_dict() if invoice.is_return and invoice.return_against else None
    if original:
        original_name = frappe.db.get_value("Addons E Invoice Submission", {"sales_invoice": invoice.return_against,
            "connection": connection.name, "environment": connection.environment, "status": "Approved"}, "name")
        if not original_name:
            frappe.throw("Original invoice must have an approved e-invoice submission on this connection")
        original_submission = frappe.get_doc("Addons E Invoice Submission", original_name)
        original_payload = json.loads(original_submission.request_json)
        original["posting_date"] = (original_payload["Invoice"]["IssueDate"] if connection.provider == "Fynamics" else original_payload["issue_date"])
    try:
        payload, expected = build_payload(data, customer, address, country, connection.as_dict(), get_system_timezone(), original)
    except (MappingError, ValueError) as exc:
        frappe.throw(str(exc))
    if connection.provider == "Fynamics":
        from addons_einvoicing.fynamics import map_payload
        from addons_einvoicing.fynamics_service import supplier_party
        payload = map_payload(payload, expected, supplier_party(connection))
    if len(canonical(payload).encode()) > 8 * 1024 * 1024:
        frappe.throw("Invoice JSON exceeds 8 MB")
    return payload, expected


def prepare(invoice, connection):
    from addons_einvoicing.sources import source_field
    field = source_field(invoice.doctype)
    frappe.db.sql(f"select name from `tab{invoice.doctype}` where name=%s for update", invoice.name)
    if frappe.db.get_value(invoice.doctype, invoice.name, "docstatus") != 1:
        frappe.throw("Only submitted invoices can be queued")
    key = digest([invoice.doctype, invoice.name, connection.environment]) if field == "purchase_invoice" else digest([invoice.name, connection.environment])
    existing = frappe.db.get_value("Addons E Invoice Submission", {"source_key": key}, "name")
    if existing:
        return frappe.get_doc("Addons E Invoice Submission", existing)
    payload, expected = build(invoice, connection)
    doc = frappe.get_doc({"doctype": "Addons E Invoice Submission", "source_key": key,
        "company": invoice.company, field: invoice.name, "connection": connection.name,
        "environment": connection.environment, "provider": connection.provider, "provider_account_id": connection.client_id,
        "supplier_trn": frappe.db.get_value("Company", invoice.company, "tax_id") if connection.provider == "Fynamics" else None, "org_id": connection.org_id,
        "business_profile_id": connection.business_profile_id, "api_version": connection.api_version,
        "document_kind": "purchase-invoices" if field == "purchase_invoice" else ("sales-credit-notes" if invoice.is_return else "sales-invoices"),
        "status": "Queued", "operation": "Create", "request_json": canonical(payload),
        "expected_json": canonical(expected), "payload_hash": digest(payload), "attempts": 0})
    internal_save(doc)
    enqueue(doc.name)
    return doc


def enqueue(name, method="send"):
    frappe.enqueue(f"addons_einvoicing.jobs.{method}", submission=name, queue="short",
                   timeout=120, enqueue_after_commit=True, job_name=f"ardentax:{method}:{name}")


def audit(doc, action, detail):
    internal_save(frappe.get_doc({"doctype": "Addons E Invoice Audit", "company": doc.company,
        "submission": doc.name, "action": action, "actor": frappe.session.user,
        "details": canonical(detail)}))


def verify_identity(doc, response):
    request = json.loads(doc.request_json)
    supplier = response.get("accounting_customer_party" if getattr(doc, "purchase_invoice", None) else "accounting_supplier_party") or {}
    if (response.get("org_id") != doc.org_id or supplier.get("profile_id") != doc.business_profile_id
            or response.get("document_number") != request["document_number"]
            or response.get("document_currency_code") != request["document_currency_code"]):
        raise ValueError("Provider document identity does not match company/profile/number/currency")
    if getattr(doc, "purchase_invoice", None):
        expected_supplier = request["accounting_supplier_party"]
        actual_supplier = response.get("accounting_supplier_party") or {}
        if response.get("invoice_type_code") != "389" or any(actual_supplier.get(k) != expected_supplier.get(k) for k in ("endpoint_id", "endpoint_scheme_id")):
            raise ValueError("Purchase supplier or self-billing type mismatch")
    import uuid
    uuid.UUID(response["id"])
    if doc.provider_uuid and response["id"] != doc.provider_uuid:
        raise ValueError("Provider UUID differs from the stored document")

