"""Framework-independent mapping, signing and reconciliation rules."""
import base64
import hashlib
import hmac
import json
import re
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo


class MappingError(ValueError):
    pass


def number(value):
    try:
        result = Decimal(str(value or 0))
    except Exception as exc:
        raise MappingError("Invalid numeric value") from exc
    if not result.is_finite():
        raise MappingError("Non-finite numeric value")
    return result


def money(value):
    return number(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def signature(secret, raw):
    return base64.b64encode(hmac.new(secret.encode(), raw, hashlib.sha256).digest()).decode()


def verify_signature(secret, raw, supplied):
    return bool(secret and supplied) and hmac.compare_digest(signature(secret, raw), supplied)


def required(obj, key, label=None):
    value = obj.get(key)
    if value is None or not str(value).strip():
        raise MappingError(f"{label or key} is required")
    return str(value).strip()


def party(customer, address, country_code):
    if customer.get("customer_type") != "Company":
        raise MappingError("This release supports business customers only; individual customer classification needs provider confirmation")
    country_code = country_code.upper()
    if not re.fullmatch(r"[A-Z]{2}", country_code):
        raise MappingError("Country must have an ISO alpha-2 code")
    postal = {
        "street_name": required(address, "address_line1", "Billing street"),
        "city_name": required(address, "city", "Billing city"),
        "country_subentity": required(address, "custom_addons_einv_region", "Ardentax region/emirate code"),
        "country": required(address, "country"), "country_code": country_code,
    }
    if country_code == "AE" and postal["country_subentity"] not in {"DXB", "AUH", "SHJ", "UAQ", "FUJ", "AJM", "RAK"}:
        raise MappingError("Invalid UAE emirate code")
    if address.get("address_line2"):
        postal["additional_street_name"] = address["address_line2"]
    if address.get("pincode"):
        postal["postal_zone"] = address["pincode"]
    out = {
        "name": required(customer, "customer_name"),
        "party_name": required(customer, "custom_addons_einv_legal_name", "Customer legal name"),
        "email": required(customer, "custom_addons_einv_email", "Customer e-invoice email"),
        "endpoint_id": required(customer, "custom_addons_einv_endpoint_id", "Customer Peppol endpoint"),
        "endpoint_scheme_id": required(customer, "custom_addons_einv_endpoint_scheme", "Customer endpoint scheme"),
        "postal_address": postal,
    }
    registration = customer.get("custom_addons_einv_registration_id")
    registration_type = customer.get("custom_addons_einv_registration_type")
    if bool(registration) != bool(registration_type):
        raise MappingError("Buyer registration ID and registration type must be supplied together")
    for source, target in {
        "custom_addons_einv_telephone": "telephone",
        "custom_addons_einv_registration_id": "company_id",
        "custom_addons_einv_registration_type": "scheme_agency_id",
        "custom_addons_einv_registration_authority": "authority_name",
    }.items():
        if customer.get(source):
            out[target] = str(customer[source]).strip()
    # Accept a copied full Peppol ID without duplicating its scheme in the API.
    if ":" in out["endpoint_id"]:
        scheme, endpoint = out["endpoint_id"].split(":", 1)
        if scheme != out["endpoint_scheme_id"] or not endpoint or ":" in endpoint:
            raise MappingError("Customer Peppol ID does not match the endpoint scheme")
        out["endpoint_id"] = endpoint
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", out["email"]):
        raise MappingError("Invalid customer e-invoice email")
    if country_code == "AE":
        tin = required(customer, "custom_addons_einv_tin", "Customer TIN")
        if not re.fullmatch(r"1\d{9}", tin):
            raise MappingError("UAE business TIN must be 10 digits starting with 1")
        out["tin"] = tin
        if customer.get("tax_id"):
            trn = str(customer["tax_id"]).strip()
            if not re.fullmatch(r"1\d{12}03", trn):
                raise MappingError("VAT TRN must be 15 digits starting with 1 and ending with 03")
            out["party_tax_scheme"] = {"company_id": trn, "tax_scheme": "VAT"}
    return out


def build_payload(invoice, customer, address, country_code, config, source_timezone, original=None):
    """Map a deliberately bounded ERP accounting shape; reject unsupported shapes."""
    inv = invoice
    is_return = bool(inv.get("is_return"))
    currency = required(inv, "currency")
    if inv.get("is_pos") or number(inv.get("write_off_amount")):
        raise MappingError("POS and write-off invoices are not supported in this release")
    if inv.get("is_debit_note"):
        raise MappingError("Debit notes need a separately approved mapping")
    if number(inv.get("discount_amount")) and inv.get("apply_discount_on") != "Net Total":
        raise MappingError("Additional discounts must apply on Net Total")
    if number(inv.get("total_advance")) or number(inv.get("paid_amount")):
        raise MappingError("Invoices with advances/prepayments require a separately validated mapping")
    flags = inv.get("custom_addons_einv_profile_execution_id") or "00000000"
    if flags not in {"00000000", "00000001", "00000010", "00000011", "01000000"}:
        raise MappingError("Supported profiles: standard, export, e-commerce, export e-commerce, or deemed supply")
    doc_type = inv.get("custom_addons_einv_type_code") or "380"
    if doc_type not in {"380", "480"}:
        raise MappingError("Invoice type must be 380 or 480")
    buyer = party(customer, address, country_code)
    if flags[-1] == "1" and country_code.upper() == "AE":
        raise MappingError("Export buyer must be outside UAE")
    if flags == "01000000":
        if config.get("environment") == "Production":
            raise MappingError("Deemed Supply requires provider contract verification before production use")
        if config.get("provider") == "Fynamics":
            raise MappingError("Deemed Supply is currently supported only by ArdentaxIT")
        if country_code.upper() != "AE" or is_return:
            raise MappingError("Deemed Supply currently supports domestic UAE invoices only")
        # The sandbox-generated INV-47 uses this endpoint for Deemed Supply.
        # Keep the customer's real endpoint unchanged in the master record.
        buyer["endpoint_id"], buyer["endpoint_scheme_id"] = "9900000097", "0235"
    if buyer["endpoint_id"] in {"9900000097", "9900000099"} and not ((flags[-1] == "1" and buyer["endpoint_id"] == "9900000099") or (flags == "01000000" and buyer["endpoint_id"] == "9900000097")):
        raise MappingError("Substitute endpoint does not match the transaction profile")
    taxes = inv.get("taxes") or []
    if len(taxes) > 1 or any(t.get("charge_type") != "On Net Total" for t in taxes):
        raise MappingError("Only one On Net Total VAT row is supported; freight/compound taxes need a separate mapping")
    tax_row = taxes[0] if taxes else {}
    maps = config.get("tax_mappings") or []
    uoms = {m["uom"]: m["unit_code"] for m in config.get("uom_mappings") or []}
    lines, line_total, tax_total = [], Decimal(0), Decimal(0)
    for index, item in enumerate(inv.get("items") or [], 1):
        qty, net = number(item.get("qty")), number(item.get("net_amount"))
        if (is_return and (qty >= 0 or net > 0)) or (not is_return and (qty <= 0 or net < 0)):
            raise MappingError(f"Line {index}: invalid quantity/amount sign")
        qty, net = abs(qty), abs(net)
        template = item.get("item_tax_template") or ""
        matched = [m for m in maps if (m.get("item_tax_template") or "") == template]
        if len(matched) != 1:
            raise MappingError(f"Line {index}: configure exactly one tax mapping for {template or 'default'}")
        mapping = matched[0]
        rate = number(mapping.get("rate"))
        actual_rates = item.get("item_tax_rate") or {}
        if isinstance(actual_rates, str):
            actual_rates = json.loads(actual_rates)
        actual = number(actual_rates.get(tax_row.get("account_head"), tax_row.get("rate", 0)))
        if actual != rate:
            raise MappingError(f"Line {index}: mapped rate differs from ERP tax rate")
        category = mapping.get("category")
        if category not in {"S", "Z", "E", "O"} or rate < 0 or (category != "S" and rate != 0):
            raise MappingError(f"Line {index}: unsupported tax category/rate")
        if category == "S" and rate != Decimal(5):
            raise MappingError("Standard UAE VAT mapping must be 5%")
        if doc_type == "480" and category == "S":
            raise MappingError("Type 480 cannot contain standard-rated lines")
        tax = {"id": category, "percent": float(rate), "tax_scheme": "VAT"}
        if category == "E":
            tax["tax_exemption_reason"] = required(mapping, "exemption_reason", "Tax exemption reason")
            tax["tax_exemption_reason_code"] = required(mapping, "exemption_code", "Tax exemption reason code")
        elif category in {"Z", "O"} and mapping.get("exemption_reason"):
            tax["tax_exemption_reason"] = mapping["exemption_reason"]
            if mapping.get("exemption_code"):
                tax["tax_exemption_reason_code"] = mapping["exemption_code"]
        unit = uoms.get(item.get("uom"))
        if not unit:
            raise MappingError(f"Line {index}: map UOM {item.get('uom')}")
        price = (net / qty).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        if money(qty * price) != money(net):
            raise MappingError(f"Line {index}: six-decimal price cannot preserve ERP line amount")
        lines.append({"quantity": float(qty), "unit_code": unit,
                      "name": item.get("item_name") or item.get("item_code"),
                      "description": re.sub(r"<[^>]+>", "", item.get("description") or item.get("item_name") or item.get("item_code") or "").strip(),
                      "classified_tax_category": tax,
                      "price": {"base_amount": float(price), "base_quantity": 1}})
        line_total += money(net)
        tax_total += money(net * rate / 100)
    if not lines:
        raise MappingError("At least one invoice line is required")
    if doc_type == "380" and not any(x["classified_tax_category"]["id"] == "S" for x in lines):
        raise MappingError("Type 380 requires a standard-rate line in the provider contract; confirm 480 for this scenario")
    if money(abs(number(inv.get("net_total")))) != money(line_total):
        raise MappingError("ERP net total does not match mapped lines")
    if money(abs(number(inv.get("total_taxes_and_charges")))) != money(tax_total):
        raise MappingError("ERP tax total differs from mapped line VAT; review rounding/tax setup")
    gross = money(line_total + tax_total)
    if gross != money(abs(number(inv.get("grand_total")))):
        raise MappingError("ERP grand total differs from mapped amounts")
    posting = f"{inv['posting_date']} {inv.get('posting_time') or '00:00:00'}"
    issued = datetime.fromisoformat(posting).replace(tzinfo=ZoneInfo(source_timezone)).astimezone(ZoneInfo("Asia/Dubai"))
    payload = {
        "document_number": required(inv, "name"), "issue_date": issued.date().isoformat(),
        "issue_time": issued.strftime("%H:%M:%S"), "profile_execution_id": flags,
        "document_currency_code": currency, "accounting_customer_party": buyer,
        "document_lines": lines, "document_source": "ERPNext",
    }
    rounding = Decimal(0) if inv.get("disable_rounded_total") else abs(number(inv.get("rounded_total"))) - gross
    if not inv.get("disable_rounded_total") and not inv.get("rounded_total"):
        rounding = Decimal(0)
    payload["payable_rounding_amount"] = float(rounding)
    if is_return:
        if not original or original.get("name") != inv.get("return_against") or original.get("company") != inv.get("company") or original.get("currency") != currency or original.get("customer") != inv.get("customer"):
            raise MappingError("Credit note must reference an original invoice with matching company, customer and currency")
        if not config.get("credit_notes_verified"):
            raise MappingError("Confirm credit-note signs and reference semantics with ArdentaxIT in sandbox, then enable credit notes on the connection")
        reason = required(inv, "custom_addons_einv_discrepancy", "Credit-note discrepancy code")
        if reason not in {"DL8.61.1.A", "DL8.61.1.B", "DL8.61.1.C", "DL8.61.1.D", "DL8.61.1.E", "VD"}:
            raise MappingError("Invalid credit-note discrepancy code")
        payload.update(credit_note_type_code="381" if doc_type == "380" else "81", discrepancy_response=reason,
                       billing_reference=[{"id": original["name"], "issue_date": str(original["posting_date"])}])
    else:
        payload.update(invoice_type_code=doc_type, due_date=required(inv, "due_date"),
                       payment_means=[{"payment_means_code": required(inv, "custom_addons_einv_payment_code", "Payment means code")}])
    if flags[-1] == "1" or flags[-2] == "1":
        shipping = inv.get("_delivery_address")
        if not shipping:
            raise MappingError("Export/e-commerce requires a structured shipping address")
        payload["delivery"] = {"delivery_location": {"address": shipping}}
        if flags[-1] == "1" and shipping.get("country_code") == "AE":
            raise MappingError("Export delivery must be outside UAE")
    if inv.get("custom_addons_einv_supply_date"):
        payload.setdefault("delivery", {})["actual_delivery_date"] = str(inv["custom_addons_einv_supply_date"])
    if currency != "AED":
        rate = number(inv.get("custom_addons_einv_aed_rate"))
        if rate <= 0:
            raise MappingError("Provide AED per invoice-currency unit in Ardentax AED Exchange Rate")
        payload.update(tax_currency_code="AED", tax_exchange_rate={"source_currency_code": currency, "target_currency_code": "AED", "calculation_rate": float(rate)})
    expected = {"tax_exclusive_amount": float(line_total), "tax_amount": float(tax_total),
                "tax_inclusive_amount": float(gross), "payable_amount": float(gross + rounding)}
    return payload, expected


def reconcile(response, expected):
    return [f"{key}: expected {money(value)}, received {response.get(key, 'missing')}"
            for key, value in expected.items()
            if response.get(key) is None or money(response[key]) != money(value)]


def processing_state(response):
    status = ((response.get("meta_info") or {}).get("peppol_status") or {})
    state = {"APPROVED": "Approved", "REJECTED": "Rejected", "VALIDATION_FAILED": "Validation Failed", "PENDING": "Processing"}.get(status.get("overall_status"), "Created")
    return state, status
