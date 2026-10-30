"""Fynamics lifecycle, isolated from ArdentaxIT routes and response semantics."""
import json
import re
import uuid

import frappe
from frappe.utils import add_to_date, get_datetime, now_datetime

from addons_einvoicing.client import APIError
from addons_einvoicing.domain import canonical, digest, required
from addons_einvoicing.fynamics import CREATE, STATUS, artifact_path, state, verify_signature
from addons_einvoicing.service import audit, client, connection_for, internal_save


def supplier_party(config):
    company = frappe.get_doc('Company', config.company)
    trn = required(company, 'tax_id', 'Company VAT TRN')
    if not re.fullmatch(r'1\d{12}03', trn):
        frappe.throw('Company VAT TRN must have 15 digits, start with 1 and end with 03')
    address_name = required(config, 'supplier_address', 'Fynamics company billing address')
    if not frappe.db.exists('Dynamic Link', {'parenttype': 'Address', 'parent': address_name, 'link_doctype': 'Company', 'link_name': company.name}):
        frappe.throw('Fynamics supplier address must be linked to this company')
    address = frappe.get_doc('Address', address_name)
    country = frappe.db.get_value('Country', address.country, 'code') or ''
    region = required(address, 'custom_addons_einv_region', 'Company address emirate code')
    if country.upper() != 'AE' or region not in {'DXB', 'AUH', 'SHJ', 'UAQ', 'FUJ', 'AJM', 'RAK'}:
        frappe.throw('Fynamics supplier must have a UAE address and valid emirate code')
    email = required(config, 'supplier_email', 'Supplier email')
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email): frappe.throw('Invalid supplier email')
    return {'schemeID': required(config, 'supplier_scheme'), 'EndpointID': required(config, 'supplier_endpoint'),
        'PartyName': company.company_name, 'PartyTaxCompanyID': trn, 'PartyTaxCode': 'VAT',
        'PostalAddress': {'StreetName': required(address, 'address_line1'), 'CityName': required(address, 'city'), 'CountrySubentity': region, 'CountryCode': 'AE'},
        'PartyLegalEntity': {'RegistrationName': company.company_name, 'CompanyID': required(config, 'supplier_registration'),
            'schemeAgencyID': required(config, 'supplier_registration_scheme'), 'schemeAgencyName': required(config, 'supplier_authority')},
        'Contact': {'Email': email}}


def apply_status(doc, response):
    status, codes = state(response, doc.provider_uuid)
    doc.status = status
    doc.overall_status = response['documentStatus']
    doc.participant_status, doc.fta_status = codes
    doc.response_json = canonical(response)
    doc.validation_json = canonical((response.get('from_c2') or {}).get('validationResults') or [])
    doc.reconciliation_note = 'Fynamics status API does not return invoice amounts. ERP totals are frozen in the request; verify downloaded documents in sandbox.'
    doc.last_error = 'Fynamics reported a failed transmission or rejection; inspect response details.' if status == 'Rejected' else ''
    doc.last_checked_at = now_datetime()
    doc.next_retry_at = add_to_date(now_datetime(), minutes=5)
    internal_save(doc)
    audit(doc, 'Fynamics state', {'status': status, 'uuid': doc.provider_uuid, 'participant': codes[0], 'fta': codes[1]})


def send(submission):
    from addons_einvoicing.jobs import checked_connection, lock
    with lock(submission):
        doc = frappe.get_doc('Addons E Invoice Submission', submission)
        if doc.status not in {'Queued', 'Retry'}: return
        if doc.next_retry_at and get_datetime(doc.next_retry_at) > now_datetime(): return
        config = checked_connection(doc)
        if doc.provider_uuid or doc.operation != 'Create':
            frappe.throw('Fynamics cannot recreate or update an existing remote document')
        frappe.db.sql('select name from `tabSales Invoice` where name=%s for update', doc.sales_invoice)
        if frappe.db.get_value('Sales Invoice', doc.sales_invoice, 'docstatus') != 1:
            doc.status = 'Stopped'; internal_save(doc); return
        c = client(config)
        # Authenticate before recording a possible invoice write. OAuth failure is safe to retry manually.
        try:
            c.token()
        except APIError:
            doc.status, doc.last_error = 'Error', 'Fynamics authentication failed. Check credentials and Test Authentication before retrying.'
            internal_save(doc); return
        doc.status = 'Sending'; doc.attempts = (doc.attempts or 0) + 1; doc.last_attempt_at = now_datetime()
        internal_save(doc); audit(doc, 'Attempt started', {'provider': 'Fynamics', 'payload_hash': doc.payload_hash, 'attempt': doc.attempts})
        frappe.db.commit()
        try:
            response = c.request('POST', CREATE, payload=json.loads(doc.request_json))
            # The documented create response binds only a UUID to this exact request, not final approval.
            remote_id = str(uuid.UUID(response['uuid']))
            doc.provider_uuid = remote_id
            doc.external_key = digest(['Fynamics', doc.connection, doc.environment, remote_id])
            doc.response_json = canonical(response)
            doc.status, doc.overall_status = 'Processing', 'QUEUED'
            doc.reconciliation_note = 'C2 accepted and queued. Final C3/C5 approval and provider amount verification remain outstanding.'
            doc.last_error = ''; doc.next_retry_at = add_to_date(now_datetime(), minutes=1)
            internal_save(doc); audit(doc, 'Fynamics accepted', {'uuid': remote_id})
        except APIError as exc:
            doc.last_error = str(exc)
            if exc.uncertain: doc.status = 'Unknown'
            elif exc.status == 429:
                doc.retry_count = (doc.retry_count or 0) + 1
                doc.status = 'Retry' if doc.retry_count <= 8 else 'Error'
            else: doc.status = 'Error'
            doc.next_retry_at = add_to_date(now_datetime(), seconds=max(exc.retry_after, min(3600, 60 * 2 ** min(doc.retry_count or 0, 6))))
            internal_save(doc); audit(doc, 'Fynamics API error', {'http_status': exc.status, 'uncertain': exc.uncertain})
        except Exception:
            frappe.db.rollback()
            doc = frappe.get_doc('Addons E Invoice Submission', submission)
            doc.status, doc.last_error = 'Unknown', 'Fynamics create response could not be verified or persisted. Do not resubmit; resolve through provider support.'
            internal_save(doc); audit(doc, 'Outcome unknown', {'provider': 'Fynamics'})


def refresh(submission, strict=False):
    from addons_einvoicing.jobs import checked_connection, lock
    with lock(submission):
        doc = frappe.get_doc('Addons E Invoice Submission', submission)
        if doc.status in {'Sending', 'Queued', 'Retry', 'Stopped'}:
            if strict: raise ValueError('Submission is not ready for status polling')
            return
        config = checked_connection(doc)
        if not doc.provider_uuid:
            if doc.status == 'Unknown':
                doc.last_error = 'Fynamics has no documented sales lookup by invoice number. Resolve with provider support; automatic resubmission and UUID linking are blocked.'
                doc.next_retry_at = add_to_date(now_datetime(), hours=24); internal_save(doc)
            if strict: raise ValueError('No verified provider UUID')
            return
        try:
            response = client(config).request('GET', STATUS + str(uuid.UUID(doc.provider_uuid)))
            apply_status(doc, response)
        except (APIError, ValueError, KeyError, TypeError):
            doc.last_error = 'Fynamics status could not be verified; previous status retained.'
            doc.last_checked_at = now_datetime(); doc.next_retry_at = add_to_date(now_datetime(), minutes=10)
            internal_save(doc)
            if strict: raise


def accept(config, raw, supplied):
    if len(raw) > 256 * 1024: frappe.throw('Webhook body too large')
    if not any(verify_signature(config.get_password(f, raise_exception=False) or '', raw, supplied) for f in ('webhook_secret', 'previous_webhook_secret')):
        frappe.throw('Invalid Fynamics webhook signature', frappe.AuthenticationError)
    try:
        payload = json.loads(raw); remote_id = str(uuid.UUID(payload['messageUuid']))
        if payload['documentStatus'] not in {'SUCCESS', 'FAILED'}: raise ValueError()
    except (ValueError, KeyError, TypeError): frappe.throw('Invalid Fynamics webhook envelope')
    # Same UUID may legitimately produce multiple final updates; dedupe the whole payload.
    key = digest(['Fynamics', config.name, config.environment, payload])
    frappe.db.sql('select name from `tabAddons E Invoice Settings` where name=%s for update', config.name)
    if frappe.db.exists('Addons E Invoice Webhook Event', {'event_key': key}): return {'accepted': True, 'duplicate': True}
    event = internal_save(frappe.get_doc({'doctype': 'Addons E Invoice Webhook Event', 'company': config.company,
        'connection': config.name, 'event_key': key, 'webhook_event_id': key, 'resource_id': remote_id,
        'event_type': 'fynamics.sales.status', 'payload_json': canonical(payload), 'status': 'Pending', 'attempts': 0}))
    frappe.enqueue('addons_einvoicing.webhooks.process', event_name=event.name, timeout=120, enqueue_after_commit=True)
    return {'accepted': True, 'duplicate': False}


def process(event_name):
    with frappe.cache.lock('fynamics:event:' + event_name, timeout=150, blocking_timeout=1):
        event = frappe.get_doc('Addons E Invoice Webhook Event', event_name)
        if event.status == 'Processed': return
        event.attempts = (event.attempts or 0) + 1
        try:
            config = connection_for(event.company)
            if config.name != event.connection or config.provider != 'Fynamics': raise ValueError('Connection changed')
            linked = frappe.db.get_value('Addons E Invoice Submission', {'provider': 'Fynamics', 'connection': config.name, 'provider_uuid': event.resource_id}, 'name')
            if not linked:
                raise ValueError('Unmatched UUID retained for review, never attached using unverified invoice identity')
            # Poll the authenticated fixed endpoint, never trust payload URLs or stale replayed statuses.
            refresh(linked, strict=True)
            event.status, event.last_error = 'Processed', ''
        except Exception:
            event.status, event.last_error = 'Error', 'Fynamics event could not be matched or refreshed. Inspect provider status and retry.'
            event.next_retry_at = add_to_date(now_datetime(), minutes=min(60, 2 ** event.attempts))
        internal_save(event)


def download(doc, config):
    from frappe.utils.file_manager import save_file
    c = client(config)
    response = c.request('GET', STATUS + str(uuid.UUID(doc.provider_uuid)))
    apply_status(doc, response)
    saved = {}
    for key, field, kind in [('print_url', 'pdf_file', 'pdf'), ('compliance_url', 'compliance_file', 'compliance')]:
        if doc.get(field): saved[field] = doc.get(field); continue
        if not response.get(key): continue
        path = artifact_path(response[key], c.base, kind)
        body, mime = c.request('GET', path, binary=True)
        if kind == 'pdf':
            if 'application/pdf' not in mime.lower() or not body.startswith(b'%PDF-'): raise ValueError('Invalid Fynamics PDF')
            extension = 'pdf'
        elif body.startswith(b'PK\x03\x04') and any(t in mime.lower() for t in ('zip', 'octet-stream')):
            extension = 'zip'
        elif 'xml' in mime.lower() and body.lstrip().startswith(b'<'):
            extension = 'xml'
        else: raise ValueError('Unsupported Fynamics compliance artifact type')
        file = save_file(f'fynamics-{doc.name}.{extension}', body, doc.doctype, doc.name, is_private=1)
        doc.set(field, file.file_url); saved[field] = file.file_url
    internal_save(doc)
    if not saved: frappe.throw('Fynamics has not made any artifacts available yet')
    audit(doc, 'Fynamics artifacts downloaded', {'fields': list(saved)})
    return saved
