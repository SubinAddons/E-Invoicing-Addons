import json
from urllib.parse import quote

import frappe

from addons_einvoicing.domain import canonical, digest
from addons_einvoicing.permissions import require_operator
from addons_einvoicing.service import audit, build, client, connection_for, enqueue, internal_save, prepare


def source(name):
    invoice = frappe.get_doc("Sales Invoice", name)
    require_operator(invoice)
    return invoice


def submission_doc(name):
    doc = frappe.get_doc("Addons E Invoice Submission", name)
    doc.check_permission("read")
    source(doc.sales_invoice)
    return doc


@frappe.whitelist(methods=["POST"])
def preview(sales_invoice):
    invoice = source(sales_invoice)
    config = connection_for(invoice.company, active=False)
    payload, expected = build(invoice, config)
    return {"payload": payload, "expected": expected, "environment": config.environment}


@frappe.whitelist(methods=["POST"])
def queue_invoice(sales_invoice):
    invoice = source(sales_invoice)
    if not invoice.get("custom_addons_einv_enabled"):
        frappe.throw("Enable E-Invoicing on this invoice first")
    return prepare(invoice, connection_for(invoice.company)).name


@frappe.whitelist()
def invoice_status(sales_invoice):
    invoice = frappe.get_doc("Sales Invoice", sales_invoice)
    invoice.check_permission("read")
    if not set(frappe.get_roles()) & {"Addons E Invoice Operator", "System Manager"}:
        return []
    return frappe.get_list("Addons E Invoice Submission", filters={"sales_invoice": invoice.name},
        fields=["name", "status", "environment", "provider_uuid", "last_error"], order_by="creation desc")


@frappe.whitelist(methods=["POST"])
def refresh_status(submission):
    doc = submission_doc(submission)
    enqueue(doc.name, "refresh")
    return {"queued": True}


@frappe.whitelist(methods=["POST"])
def correct_and_retry(submission):
    from addons_einvoicing.jobs import lock
    with lock(submission):
        doc = submission_doc(submission)
        if doc.status not in {"Error", "Validation Failed"}:
            frappe.throw("Correction is allowed only for a definite API error or VALIDATION_FAILED. Reconcile uncertain outcomes first.")
        if doc.provider == "Fynamics" and doc.provider_uuid:
            frappe.throw("Fynamics has no documented update/resubmission endpoint; resolve this document with the provider")
        if doc.provider_uuid and doc.overall_status != "VALIDATION_FAILED":
            frappe.throw("The provider document is not eligible for resubmission")
        invoice = source(doc.sales_invoice)
        if invoice.docstatus != 1:
            frappe.throw("Invoice must remain submitted")
        payload, expected = build(invoice, connection_for(doc.company))
        if canonical(expected) != doc.expected_json:
            frappe.throw("Accounting amounts changed; use the credit-note workflow")
        audit(doc, "Payload corrected", {"old_hash": doc.payload_hash, "old_payload": json.loads(doc.request_json), "new_hash": digest(payload)})
        doc.request_json, doc.payload_hash = canonical(payload), digest(payload)
        doc.operation = "Resubmit" if doc.provider_uuid else "Create"
        doc.status, doc.last_error, doc.next_retry_at, doc.retry_count = "Queued", "", None, 0
        internal_save(doc)
        enqueue(doc.name)
    return {"queued": True}


@frappe.whitelist(methods=["POST"])
def download_artifacts(submission):
    from addons_einvoicing.jobs import checked_connection, lock, route
    from frappe.utils.file_manager import save_file
    with lock(submission):
        doc = submission_doc(submission)
        if not doc.provider_uuid:
            frappe.throw("No provider document is available")
        connection = checked_connection(doc)
        if doc.provider == "Fynamics":
            from addons_einvoicing.fynamics_service import download
            return download(doc, connection)
        c = client(connection)
        for field, suffix, extension, mime in (("pdf_file", "download-pdf", "pdf", "application/pdf"), ("xml_file", "xml", "xml", "xml")):
            if doc.get(field):
                continue
            data, content_type = c.request("GET", route(doc) + "/" + quote(doc.provider_uuid, safe="") + "/" + suffix, binary=True)
            if mime not in content_type.lower():
                frappe.throw(f"Unexpected {extension} response content type")
            if extension == "pdf" and not data.startswith(b"%PDF-"):
                frappe.throw("Provider PDF response is not a PDF")
            file = save_file(f"ardentax-{doc.name}.{extension}", data, "Addons E Invoice Submission", doc.name, is_private=1)
            doc.set(field, file.file_url)
        internal_save(doc)
        audit(doc, "Artifacts downloaded", {"pdf": bool(doc.pdf_file), "xml": bool(doc.xml_file)})
        return {"pdf_file": doc.pdf_file, "xml_file": doc.xml_file}


@frappe.whitelist(methods=["POST"])
def test_connection(connection):
    frappe.only_for("System Manager")
    doc = frappe.get_doc("Addons E Invoice Settings", connection)
    doc.check_permission("write")
    # Read-only authentication test, never creates a tax document and never returns the token.
    client(doc).token(refresh=True)
    return {"authenticated": True, "environment": doc.environment}


@frappe.whitelist(methods=["POST"])
def link_existing(submission, provider_uuid):
    """Resolve an unknown outcome using a provider UUID; this performs only a GET."""
    import uuid
    from addons_einvoicing.jobs import apply_response, checked_connection, lock, route
    provider_uuid = str(uuid.UUID(provider_uuid))
    with lock(submission):
        doc = submission_doc(submission)
        if doc.provider == "Fynamics":
            frappe.throw("Fynamics status does not expose invoice identity; automatic linking of an unknown UUID is unavailable. Resolve it with provider support; do not resubmit.")
        if doc.status != "Unknown" or doc.provider_uuid:
            frappe.throw("Manual linking is only for unknown submissions without a provider UUID")
        response = client(checked_connection(doc)).request("GET", route(doc) + "/" + provider_uuid)
        apply_response(doc, response)
        audit(doc, "Existing document linked", {"uuid": provider_uuid})
    return {"status": doc.status}


@frappe.whitelist(methods=["POST"])
def retry_webhook(event):
    doc = frappe.get_doc("Addons E Invoice Webhook Event", event)
    doc.check_permission("read")
    if not set(frappe.get_roles()) & {"System Manager", "Addons E Invoice Operator"}:
        frappe.throw("Addons E Invoice Operator role required", frappe.PermissionError)
    if doc.status != "Error":
        frappe.throw("Only failed webhook events can be retried")
    doc.status, doc.attempts, doc.next_retry_at = "Pending", 0, None
    internal_save(doc)
    frappe.enqueue("addons_einvoicing.webhooks.process", event_name=doc.name, timeout=120, enqueue_after_commit=True)
    return {"queued": True}


@frappe.whitelist(allow_guest=True, methods=["POST"])
def webhook(connection=None, **kwargs):
    from addons_einvoicing.webhooks import accept
    if not connection:
        frappe.throw("Connection is required")
    config = frappe.get_doc("Addons E Invoice Settings", connection)
    if config.provider == "Fynamics":
        from addons_einvoicing.fynamics_service import accept as accept_fynamics
        return accept_fynamics(config, frappe.request.get_data(), frappe.request.headers.get("X-Webhook-Signature", ""))
    return accept(connection, frappe.request.get_data(), frappe.request.headers.get("X-HMAC-Signature", ""))


@frappe.whitelist()
def dashboard(company=None, environment=None, days=30):
    from frappe.utils import add_days, nowdate
    frappe.only_for(["System Manager", "Addons E Invoice Operator"])
    days = int(days)
    if days not in {7, 30, 90}:
        frappe.throw("Choose 7, 30 or 90 days")
    if environment and environment not in {"Sandbox", "Production"}:
        frappe.throw("Invalid environment")
    companies = frappe.get_list("Company", pluck="name", limit_page_length=0)
    if company and company not in companies:
        frappe.throw("Company access denied", frappe.PermissionError)
    filters = {"company": company or ["in", companies], "creation": [">=", add_days(nowdate(), 1-days)]}
    if environment:
        filters["environment"] = environment
    doctype = "Addons E Invoice Submission"
    counts = frappe.get_list(doctype, filters=filters, fields=["status", "count(name) as total"], group_by="status", limit_page_length=0)
    recent = frappe.get_list(doctype, filters=filters,
        fields=["name", "sales_invoice", "company", "provider", "status", "environment", "modified"], order_by="modified desc", limit_page_length=20)
    trend = frappe.get_list(doctype, filters=filters,
        fields=["date(creation) as day", "count(name) as total"], group_by="date(creation)", order_by="day asc", limit_page_length=0)
    attention = frappe.get_list(doctype, filters={**filters, "status": ["in", ["Unknown", "Mismatch", "Error", "Rejected", "Validation Failed"]]},
        fields=["name", "sales_invoice", "status"], order_by="modified desc", limit_page_length=5)
    settings = []
    can_configure = "System Manager" in frappe.get_roles()
    if can_configure:
        settings_filters = {"company": company or ["in", companies]}
        if environment: settings_filters["environment"] = environment
        settings = frappe.get_list("Addons E Invoice Settings", filters=settings_filters,
            fields=["name", "company", "provider", "environment", "enabled", "auto_submit"], limit_page_length=0)
    return {"counts": counts, "recent": recent, "trend": trend, "attention": attention,
        "companies": companies, "settings": settings, "can_configure": can_configure,
        "from_date": add_days(nowdate(), 1-days), "to_date": nowdate(), "days": days}


@frappe.whitelist(methods=["POST"])
def queue_invoices(sales_invoices):
    names = frappe.parse_json(sales_invoices)
    if not isinstance(names, list) or not names or len(names) > 50 or any(not isinstance(n, str) for n in names):
        frappe.throw("Select between 1 and 50 saved Sales Invoices")
    names = list(dict.fromkeys(names))
    # Validate the entire selection before creating any records or queue callbacks.
    for name in names:
        invoice = source(name)
        if invoice.docstatus != 1 or not invoice.get("custom_addons_einv_enabled"):
            frappe.throw("Every selected invoice must be submitted and enabled for e-invoicing")
        build(invoice, connection_for(invoice.company))
    return [queue_invoice(name) for name in names]
