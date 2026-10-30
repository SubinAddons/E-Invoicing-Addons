import json
import random
from urllib.parse import quote

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime

from addons_einvoicing.client import APIError
from addons_einvoicing.domain import canonical, digest, processing_state, reconcile
from addons_einvoicing.service import audit, client, connection_for, internal_save, verify_identity


def lock(name):
    return frappe.cache.lock("ardentax:submission:" + name, timeout=150, blocking_timeout=1)


def route(doc):
    if doc.document_kind not in {"sales-invoices", "sales-credit-notes"}:
        raise ValueError("Unsupported document kind")
    return "/api/" + doc.document_kind


def checked_connection(doc):
    connection = connection_for(doc.company)
    if (doc.provider or "ArdentaxIT") != connection.provider:
        raise ValueError("Submission provider cannot change")
    if doc.provider == "Fynamics":
        if connection.client_id != doc.provider_account_id or frappe.db.get_value("Company", doc.company, "tax_id") != doc.supplier_trn:
            raise ValueError("Fynamics account or supplier TRN changed")
    for key in ("environment", "org_id", "business_profile_id", "api_version"):
        if connection.get(key) != doc.get(key):
            raise ValueError("Connection identity changed; submission is blocked")
    if connection.name != doc.connection:
        raise ValueError("Connection no longer matches the submission")
    return connection


def apply_response(doc, response):
    verify_identity(doc, response)
    doc.provider_uuid = response["id"]
    doc.external_key = digest([doc.environment, doc.org_id, doc.provider_uuid])
    doc.response_json = canonical(response)
    doc.is_phase2 = bool(response.get("is_phase2_document"))
    state, status = processing_state(response)
    doc.overall_status = status.get("overall_status")
    doc.participant_status = status.get("participant_status")
    doc.fta_status = status.get("fta_status")
    doc.validation_json = canonical(status.get("validation_results") or [])
    mismatches = reconcile(response, json.loads(doc.expected_json))
    doc.status = "Mismatch" if mismatches else state
    doc.last_error = "\n".join(mismatches) if mismatches else ""
    doc.last_checked_at = now_datetime()
    doc.next_retry_at = add_to_date(now_datetime(), minutes=5)
    internal_save(doc)
    audit(doc, "Provider state", {"status": doc.status, "uuid": doc.provider_uuid,
        "overall": doc.overall_status, "participant": doc.participant_status, "fta": doc.fta_status,
        "mismatches": mismatches})


def send(submission):
    if frappe.db.get_value("Addons E Invoice Submission", submission, "provider") == "Fynamics":
        from addons_einvoicing.fynamics_service import send as fynamics_send
        return fynamics_send(submission)
    with lock(submission):
        doc = frappe.get_doc("Addons E Invoice Submission", submission)
        if doc.status not in {"Queued", "Retry"}:
            return
        if doc.next_retry_at and get_datetime(doc.next_retry_at) > now_datetime():
            return
        connection = checked_connection(doc)
        # Same row lock as cancellation; either cancel wins or the durable Sending marker wins.
        frappe.db.sql("select name from `tabSales Invoice` where name=%s for update", doc.sales_invoice)
        if frappe.db.get_value("Sales Invoice", doc.sales_invoice, "docstatus") != 1:
            doc.status, doc.last_error = "Stopped", "ERP invoice is no longer submitted"
            internal_save(doc)
            return
        c = client(connection)
        path, method = route(doc) + "/" + quote(doc.business_profile_id, safe=""), "POST"
        if doc.operation == "Resubmit":
            # Re-fetch eligibility immediately before PUT; queued state may be old.
            current = c.request("GET", route(doc) + "/" + quote(doc.provider_uuid, safe=""))
            verify_identity(doc, current)
            if processing_state(current)[1].get("overall_status") != "VALIDATION_FAILED":
                apply_response(doc, current)
                return
            path = route(doc) + "/" + quote(doc.provider_uuid, safe="") + "/" + quote(doc.business_profile_id, safe="")
            method = "PUT"
        doc.status = "Sending"
        doc.attempts = (doc.attempts or 0) + 1
        doc.last_attempt_at = now_datetime()
        internal_save(doc)
        audit(doc, "Attempt started", {"method": method, "payload_hash": doc.payload_hash, "attempt": doc.attempts})
        # Essential: crash after remote success must not cause a second create on job retry.
        frappe.db.commit()
        try:
            response = c.request(method, path, payload=json.loads(doc.request_json))
            apply_response(doc, response)
        except APIError as exc:
            doc.last_error = str(exc)
            if exc.uncertain:
                doc.status = "Unknown"
            elif exc.status == 429:
                doc.retry_count = (doc.retry_count or 0) + 1
                doc.status = "Retry" if doc.retry_count <= 8 else "Error"
            else:
                doc.status = "Error"
            doc.next_retry_at = add_to_date(now_datetime(), seconds=max(exc.retry_after, min(3600, 30 * 2 ** min(doc.retry_count or 0, 6))) + random.randint(1, 15))
            internal_save(doc)
            audit(doc, "API error", {"http_status": exc.status, "uncertain": exc.uncertain, "validation_errors": exc.detail})
        except Exception:
            # Includes response schema/identity failures and persistence errors after a successful POST.
            frappe.db.rollback()
            doc = frappe.get_doc("Addons E Invoice Submission", submission)
            doc.status = "Unknown"
            doc.last_error = "Response could not be verified or persisted. Reconcile before any further submission."
            doc.next_retry_at = add_to_date(now_datetime(), minutes=5)
            internal_save(doc)
            audit(doc, "Outcome unknown", {"action": "Reconcile provider document"})


def refresh(submission):
    if frappe.db.get_value("Addons E Invoice Submission", submission, "provider") == "Fynamics":
        from addons_einvoicing.fynamics_service import refresh as fynamics_refresh
        return fynamics_refresh(submission)
    with lock(submission):
        doc = frappe.get_doc("Addons E Invoice Submission", submission)
        if doc.status in {"Sending", "Queued", "Retry", "Stopped"}:
            return
        c = client(checked_connection(doc))
        try:
            if doc.provider_uuid:
                response = c.request("GET", route(doc) + "/" + quote(doc.provider_uuid, safe=""))
            elif doc.status == "Unknown":
                # Lookup is deliberately read-only. Absence never authorizes a new POST.
                listing = c.request("GET", route(doc), params={"document_number": json.loads(doc.request_json)["document_number"], "page": 0, "size": 100})
                matches = []
                for candidate in listing.get("content") or []:
                    try:
                        verify_identity(doc, candidate)
                        matches.append(candidate)
                    except (ValueError, KeyError, TypeError):
                        continue
                if len(matches) != 1 or listing.get("total_pages", 1) > 1:
                    doc.last_error = "No unique verified match. Check provider dashboard/support; do not create again."
                    doc.last_checked_at = now_datetime()
                    doc.next_retry_at = add_to_date(now_datetime(), minutes=15)
                    internal_save(doc)
                    return
                response = c.request("GET", route(doc) + "/" + quote(matches[0]["id"], safe=""))
            else:
                return
            apply_response(doc, response)
        except (APIError, ValueError, KeyError, TypeError) as exc:
            doc.last_error = str(exc) if isinstance(exc, APIError) else "Provider response did not match the submission contract"
            doc.last_checked_at = now_datetime()
            doc.next_retry_at = add_to_date(now_datetime(), minutes=10)
            internal_save(doc)


def recover():
    enabled = frappe.get_all("Addons E Invoice Settings", filters={"enabled": 1}, pluck="name")
    if not enabled:
        return
    for row in frappe.get_all("Addons E Invoice Submission", filters={"connection": ["in", enabled], "status": ["in", ["Sending", "Queued", "Retry", "Unknown", "Created", "Processing", "Mismatch"]]}, fields=["name", "status", "last_attempt_at", "next_retry_at"], order_by="modified asc", limit_page_length=100):
        if row.status == "Sending":
            if row.last_attempt_at and get_datetime(row.last_attempt_at) < add_to_date(now_datetime(), minutes=-10):
                with lock(row.name):
                    doc = frappe.get_doc("Addons E Invoice Submission", row.name)
                    if doc.status == "Sending":
                        doc.status, doc.last_error = "Unknown", "Worker stopped during submission; reconciliation required"
                        internal_save(doc)
            continue
        if row.next_retry_at and get_datetime(row.next_retry_at) > now_datetime():
            continue
        from addons_einvoicing.service import enqueue
        enqueue(row.name, "send" if row.status in {"Queued", "Retry"} else "refresh")
    for event in frappe.get_all("Addons E Invoice Webhook Event", filters={"connection": ["in", enabled], "status": ["in", ["Pending", "Error"]], "attempts": ["<", 8]}, fields=["name", "next_retry_at"], order_by="modified asc", limit_page_length=100):
        if not event.next_retry_at or get_datetime(event.next_retry_at) <= now_datetime():
            frappe.enqueue("addons_einvoicing.webhooks.process", event_name=event.name, timeout=120, enqueue_after_commit=True)
