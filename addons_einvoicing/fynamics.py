"""Fynamics published enriched-sales contract, reviewed 2026-10-17.

Pure mapping and transport. Never interpret initial C2 acceptance as final approval.
"""
import base64
import hashlib
import hmac
import json
import re
import time
import uuid
from urllib.parse import urlparse

import requests

from addons_einvoicing.client import APIError, MAX_RESPONSE
from addons_einvoicing.domain import MappingError, money, number, required

BASES = {"Sandbox": "https://sandbox-uae.fynamicstax.com", "Production": "https://uae.fynamicstax.com"}
PREFIX = "/api/partner"
CREATE = PREFIX + "/sales-invoice/invoice"
STATUS = PREFIX + "/sales-invoice/get-document-status/"


def validate_base_url(value, environment):
    if environment not in BASES or value.rstrip("/") != BASES[environment]:
        raise ValueError("Use the documented Fynamics HTTPS origin for the selected environment (without /api/partner)")
    return BASES[environment]


def verify_signature(secret, raw, supplied):
    expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return bool(secret and supplied) and hmac.compare_digest(expected, supplied)


def postal(address):
    return {b: address[a] for a, b in {
        "street_name": "StreetName", "additional_street_name": "AdditionalStreetName",
        "city_name": "CityName", "postal_zone": "PostalZone", "country_subentity": "CountrySubentity",
        "country_code": "CountryCode"}.items() if address.get(a)}


def map_payload(common, expected, supplier):
    # The documented enriched-sales example is used rather than the conflicting legacy schema.
    if common["document_currency_code"] != "AED" or common["profile_execution_id"] != "00000000":
        raise MappingError("Fynamics currently supports standard domestic AED invoices; foreign currency/export/e-commerce need separate sandbox mappings")
    buyer = common["accounting_customer_party"]
    if buyer["postal_address"]["country_code"] != "AE":
        raise MappingError("Fynamics currently supports domestic UAE business buyers")
    buyer_trn = (buyer.get("party_tax_scheme") or {}).get("company_id")
    if not buyer_trn:
        raise MappingError("Fynamics domestic VAT invoices require the customer's VAT TRN")
    header = {"InvoiceNumber": common["document_number"], "IssueDate": common["issue_date"],
        "IssueTime": common["issue_time"], "InvoiceTypeCode": common.get("invoice_type_code") or common.get("credit_note_type_code"),
        "TransactionType": common["profile_execution_id"], "DocumentCurrencyCode": "AED"}
    if header["InvoiceTypeCode"] not in {"380", "381"}:
        raise MappingError("Fynamics currently supports tax invoices (380) and verified credit notes (381)")
    if common.get("due_date"): header["DueDate"] = common["due_date"]
    if common.get("discrepancy_response"): header["DiscrepancyResponse"] = common["discrepancy_response"]
    payload = {"Invoice": header, "AccountingSupplierParty": supplier,
        "AccountingCustomerParty": {"schemeID": buyer["endpoint_scheme_id"], "EndpointID": buyer["endpoint_id"],
            "PartyName": buyer["name"], "PostalAddress": postal(buyer["postal_address"]),
            "PartyTaxCompanyID": buyer_trn, "PartyTaxCode": "VAT",
            "PartyLegalEntity": {"RegistrationName": buyer["party_name"]}, "Contact": {"Email": buyer["email"]}},
        "InvoiceLine": []}
    for index, line in enumerate(common["document_lines"], 1):
        tax = line["classified_tax_category"]
        if tax["id"] != "S" or number(tax["percent"]) != 5:
            raise MappingError("Fynamics mapping currently supports 5% standard VAT; other categories need confirmed exemption fields")
        amount = money(number(line["quantity"]) * number(line["price"]["base_amount"]))
        payload["InvoiceLine"].append({"ID": str(index), "InvoicedQuantity": line["quantity"],
            "InvoicedUniteCode": line["unit_code"], "LineExtensionAmount": float(amount), "LineExtensionAmountCurrencyCode": "AED",
            "Item": {"Name": line["name"], "ClassifiedTaxCategory": [{"TaxCategoryID": "S", "TaxCategoryPercent": 5, "TaxCategorySchemeID": "VAT"}]},
            "Price": {"PriceAmount": line["price"]["base_amount"], "PriceAmountCurrencyCode": "AED", "BaseQuantity": 1, "BaseUnitCode": line["unit_code"]},
            "ItemPriceExtension": {"Amount": float(amount), "CurrencyCode": "AED", "TaxAmount": float(money(amount * number('0.05'))), "TaxAmountCurrencyCode": "AED"}})
    # VAT breakdown must also reconcile when line rounding accumulates.
    if money(number(expected["tax_exclusive_amount"]) * number('0.05')) != money(expected["tax_amount"]):
        raise MappingError("Fynamics VAT subtotal rounding differs from ERP line VAT; review invoice rounding")
    payload["TaxTotal"] = {"TaxIncludedIndicator": False, "TaxAmount": expected["tax_amount"], "TaxAmountCurrencyCode": "AED",
        "DocumentTaxAmount": expected["tax_amount"], "DocumentTaxAmountCurrencyCode": "AED",
        "DocumentTaxSubtotal": [{"TaxableAmount": expected["tax_exclusive_amount"], "TaxableAmountCurrencyCode": "AED",
            "TaxAmount": expected["tax_amount"], "TaxAmountCurrencyCode": "AED", "TaxCategoryID": "S", "TaxCategoryPercent": 5, "TaxCategorySchemeID": "VAT"}]}
    totals = {"LineExtensionAmount": expected["tax_exclusive_amount"], "TaxExclusiveAmount": expected["tax_exclusive_amount"],
        "TaxInclusiveAmount": expected["tax_inclusive_amount"], "PayableAmount": expected["payable_amount"],
        "PayableRoundingAmount": common["payable_rounding_amount"]}
    payload["LegalMonetaryTotal"] = {**totals, **{key + "CurrencyCode": "AED" for key in totals}}
    if common.get("payment_means"):
        payload["PaymentMeans"] = [{"PaymentMeansCode": p["payment_means_code"]} for p in common["payment_means"]]
    if common.get("billing_reference"):
        payload["BillingReference"] = [{"ID": p["id"], "IssueDate": p["issue_date"]} for p in common["billing_reference"]]
    if (common.get("delivery") or {}).get("actual_delivery_date"):
        payload["Delivery"] = {"ActualDeliveryDate": common["delivery"]["actual_delivery_date"]}
    return payload


def state(response, expected_uuid):
    if str(uuid.UUID(response["messageUuid"])) != expected_uuid:
        raise ValueError("Fynamics UUID does not match the submitted document")
    overall = response.get("documentStatus")
    if overall not in {"SUCCESS", "FAILED", "QUEUED"} or not isinstance(response.get("to_c5"), dict):
        raise ValueError("Unrecognized Fynamics document status")
    legs = [response.get(k) or {} for k in ("to_c3", "to_c5")]
    # Our supported domestic B2B profile owes both C3 and C5 acknowledgements.
    codes = [(leg.get("mls") or {}).get("responseCode") for leg in legs]
    failed = overall == "FAILED" or any(leg.get("isTransmissionError") or leg.get("status") == "FAILED" or code == "RE" for leg, code in zip(legs, codes))
    approved = overall == "SUCCESS" and all(code == "AP" for code in codes)
    return ("Rejected" if failed else "Approved" if approved else "Processing"), codes


def artifact_path(url, base, kind):
    parsed, origin = urlparse(url), urlparse(base)
    prefix = PREFIX + ("/sales-invoice/print-from-url/" if kind == "pdf" else "/download/compliance-from-url/")
    if (parsed.scheme != 'https' or parsed.netloc != origin.netloc or parsed.username or parsed.password
            or parsed.fragment or parsed.query or not parsed.path.startswith(prefix)
            or not re.fullmatch(r'[A-Za-z0-9_=-]+', parsed.path[len(prefix):])):
        raise ValueError("Untrusted Fynamics artifact URL")
    return parsed.path


class Client:
    def __init__(self, connection, cache, session=None):
        self.connection, self.cache = connection, cache
        self.base = validate_base_url(connection.api_base_url, connection.environment)
        self.secret = connection.get_password("client_secret")
        self.session = session or requests.Session()
        self.identity = hashlib.sha256(f'{self.base}|{connection.client_id}'.encode()).hexdigest()
        self.token_key = 'fynamics:token:' + hashlib.sha256(f'{self.identity}|{self.secret}'.encode()).hexdigest()

    def _http(self, method, path, headers, payload=None, form=None):
        write = method == 'POST' and path == CREATE
        if not path.startswith(PREFIX + '/') or any(x in path for x in ('..', '?', '#', '\\')):
            raise ValueError('Fixed relative Fynamics API path required')
        try:
            with self.session.request(method, self.base + path, headers=headers, json=payload, data=form,
                    timeout=(10, 40), stream=True, allow_redirects=False) as response:
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > MAX_RESPONSE: raise APIError('Fynamics response too large', uncertain=write)
                    chunks.append(chunk)
                body = b''.join(chunks)
                code = response.status_code
                if not 200 <= code < 300:
                    # 409 may be a duplicate already created; never automatically repeat it.
                    raise APIError(f'Fynamics returned HTTP {code}', code,
                        uncertain=write and code not in {400, 401, 403, 413, 422, 429})
                return body, response.headers.get('Content-Type', '')
        except requests.RequestException:
            raise APIError('Fynamics request failed or timed out', uncertain=write) from None

    def token(self, refresh=False):
        if refresh: self.cache.delete_value(self.token_key)
        token = self.cache.get_value(self.token_key)
        if token: return token
        with self.cache.lock(self.token_key + ':lock', timeout=60, blocking_timeout=2):
            token = self.cache.get_value(self.token_key)
            if token: return token
            basic = base64.b64encode(f'{self.connection.client_id}:{self.secret}'.encode()).decode()
            body, _ = self._http('POST', PREFIX + '/auth/authenticate',
                {'Authorization': 'Basic ' + basic, 'Content-Type': 'application/x-www-form-urlencoded'},
                form={'grant_type': 'client_credentials'})
            try:
                result = json.loads(body)
                data = result['data']
                token, ttl = data['access_token'], int(data['expires_in']) - 60
                if result.get('success') != 1 or not isinstance(token, str) or not token or ttl <= 0 or data.get('token_type', '').lower() != 'bearer': raise ValueError()
            except (ValueError, KeyError, TypeError):
                raise APIError('Unexpected Fynamics OAuth response') from None
            self.cache.set_value(self.token_key, token, expires_in_sec=min(ttl, 86400))
            return token

    def request(self, method, path, payload=None, binary=False):
        for attempt in range(2):
            token = self.token(refresh=attempt == 1)
            bucket = f'fynamics:rate:{self.identity}:{int(time.time() // 60)}'
            with self.cache.lock(bucket + ':lock', timeout=5, blocking_timeout=2):
                count = int(self.cache.get_value(bucket) or 0)
                if count >= 45: raise APIError('Local Fynamics throttle; retry later', 429, retry_after=65)
                self.cache.set_value(bucket, count + 1, expires_in_sec=120)
            try:
                body, mime = self._http(method, path, {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}, payload)
            except APIError as exc:
                if exc.status == 401 and attempt == 0: continue
                raise
            if binary: return body, mime
            try:
                result = json.loads(body)
                if not isinstance(result, dict): raise ValueError()
                return result
            except ValueError:
                raise APIError('Unexpected Fynamics JSON response', uncertain=method == 'POST') from None
