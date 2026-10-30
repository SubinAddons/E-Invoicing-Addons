import json
import uuid

import frappe
from frappe.utils import add_to_date, now_datetime

from addons_einvoicing.domain import canonical, digest, verify_signature
from addons_einvoicing.service import client, connection_for, internal_save

KINDS = {"sale.invoice": "sales-invoices", "sale.credit_note": "sales-credit-notes",
         "purchase.invoice": "purchase-invoices", "purchase.credit_note": "purchase-credit-notes"}


def accept(connection, raw, supplied):
    if len(raw) > 256 * 1024:
        frappe.throw("Webhook body too large", frappe.ValidationError)
    config = frappe.get_doc("Addons E Invoice Settings", connection)
    valid = any(verify_signature(config.get_password(field, raise_exception=False) or "", raw, supplied)
                for field in ("webhook_secret", "previous_webhook_secret"))
    if not valid:
        frappe.throw("Invalid webhook signature", frappe.AuthenticationError)
    try:
        payload = json.loads(raw)
        uuid.UUID(payload["webhook_event_id"])
        uuid.UUID(payload["resource_id"])
        event_type, action = payload["event_type"].rsplit(".", 1)
        if event_type not in KINDS or action not in {"create", "update"}:
            raise ValueError()
        if payload["org_id"] != config.org_id or payload["profile_id"] != config.business_profile_id:
            raise ValueError()
    except (ValueError, KeyError, TypeError, AttributeError):
        frappe.throw("Invalid webhook envelope or organization/profile", frappe.ValidationError)
    key = digest([config.environment, config.org_id, payload["webhook_event_id"]])
    # Unique deterministic name plus DB lock serializes duplicate deliveries through commit.
    frappe.db.sql("select name from `tabAddons E Invoice Settings` where name=%s for update", config.name)
    existing = frappe.db.get_value("Addons E Invoice Webhook Event", {"event_key": key}, "name")
    if existing:
        return {"accepted": True, "duplicate": True}
    event = internal_save(frappe.get_doc({"doctype": "Addons E Invoice Webhook Event", "company": config.company,
        "connection": config.name, "event_key": key, "webhook_event_id": payload["webhook_event_id"],
        "resource_id": payload["resource_id"], "event_type": payload["event_type"],
        "payload_json": canonical(payload), "status": "Pending", "attempts": 0}))
    frappe.enqueue("addons_einvoicing.webhooks.process", event_name=event.name, timeout=120, enqueue_after_commit=True)
    return {"accepted": True, "duplicate": False}


def process(event_name):
    connection = frappe.db.get_value("Addons E Invoice Webhook Event", event_name, "connection")
    if frappe.db.get_value("Addons E Invoice Settings", connection, "provider") == "Fynamics":
        from addons_einvoicing.fynamics_service import process as process_fynamics
        return process_fynamics(event_name)
    with frappe.cache.lock("ardentax:event:" + event_name, timeout=150, blocking_timeout=1):
        event = frappe.get_doc("Addons E Invoice Webhook Event", event_name)
        if event.status == "Processed":
            return
        config = connection_for(event.company)
        payload = json.loads(event.payload_json)
        if config.name != event.connection or payload["org_id"] != config.org_id or payload["profile_id"] != config.business_profile_id:
            raise ValueError("Webhook connection changed")
        event.attempts = (event.attempts or 0) + 1
        try:
            external = digest([config.environment, config.org_id, event.resource_id])
            linked = frappe.db.get_value("Addons E Invoice Submission", {"external_key": external}, "name")
            if linked:
                from addons_einvoicing.jobs import refresh
                refresh(linked)
            else:
                kind = KINDS[event.event_type.rsplit(".", 1)[0]]
                # Never follow resource_url from the webhook. Construct the trusted route ourselves.
                response = client(config).request("GET", f"/api/{kind}/{event.resource_id}")
                profiles = {(response.get(p) or {}).get("profile_id") for p in ("accounting_supplier_party", "accounting_customer_party")}
                if response.get("org_id") != config.org_id or response.get("id") != event.resource_id or config.business_profile_id not in profiles:
                    raise ValueError("Resource identity mismatch")
                # Store unmatched/inbound documents for review; no unsolicited GL postings.
                with frappe.cache.lock("ardentax:inbox:" + external, timeout=30, blocking_timeout=1):
                    name = frappe.db.get_value("Addons E Invoice Inbox", {"external_key": external}, "name")
                    inbox = frappe.get_doc("Addons E Invoice Inbox", name) if name else frappe.get_doc({"doctype": "Addons E Invoice Inbox", "company": config.company, "connection": config.name, "external_key": external, "provider_uuid": event.resource_id})
                    inbox.update({"document_kind": kind, "document_number": response.get("document_number"),
                                  "status": "Needs Review", "response_json": canonical(response), "last_received_at": now_datetime()})
                    internal_save(inbox)
            event.status, event.last_error = "Processed", ""
        except Exception:
            # Retry metadata remains safe; detailed API payloads are only in protected document records.
            event.status, event.last_error = "Error", "Webhook processing failed; verify connection and provider status"
            event.next_retry_at = add_to_date(now_datetime(), minutes=min(60, 2 ** event.attempts))
        internal_save(event)
