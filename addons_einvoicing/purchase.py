"""Ardentax purchase creation uses self-billing type 389, never supplier type 380."""
from copy import deepcopy
from addons_einvoicing.domain import build_payload, MappingError, required


def build_purchase_payload(invoice, supplier, address, country, config, timezone):
    if config.get("provider") != "ArdentaxIT":
        raise MappingError("Purchase submission currently supports ArdentaxIT only")
    if not invoice.get("custom_addons_einv_self_billing"):
        raise MappingError("Confirm Self Billing for this Purchase Invoice before sending to Ardentax")
    if invoice.get("is_return"):
        raise MappingError("Purchase returns require a separately validated credit-note workflow")
    if (invoice.get("custom_addons_einv_profile_execution_id") or "00000000") != "00000000":
        raise MappingError("Purchase submission currently supports the standard transaction profile only")
    if country.upper() != "AE":
        raise MappingError("Purchase submission currently supports UAE suppliers only")
    from addons_einvoicing.supplier import validate_fields
    validate_fields(supplier)
    if supplier.get("custom_addons_einv_registration_type") == "TL":
        required(supplier, "custom_addons_einv_registration_authority", "Supplier registration issuing authority")
    # Reuse line arithmetic and ERP tax validation; explicitly exchange party roles below.
    data = deepcopy(invoice)
    data["custom_addons_einv_type_code"] = "380"
    party = deepcopy(supplier)
    party["customer_name"] = supplier.get("supplier_name")
    party["customer_type"] = "Company"
    try:
        payload, expected = build_payload(data, party, address, country, config, timezone)
    except MappingError as exc:
        raise MappingError(str(exc).replace("Customer", "Supplier").replace("customer", "supplier").replace("Buyer", "Supplier")) from exc
    payload["accounting_supplier_party"] = payload.pop("accounting_customer_party")
    payload["invoice_type_code"] = "389"
    seller = payload["accounting_supplier_party"]
    for source, target in (("party_id", "party_identification_id"), ("party_scheme", "party_identification_scheme_id"), ("passport_country_code", "passport_issuing_country_code")):
        if supplier.get("custom_addons_einv_" + source):
            seller[target] = supplier["custom_addons_einv_" + source]
    for source, target in (("buyer_reference", "buyer_reference"), ("note", "note")):
        if invoice.get("custom_addons_einv_" + source):
            payload[target] = invoice["custom_addons_einv_" + source]
    code = payload["payment_means"][0]["payment_means_code"]
    if code == "30":
        payload["payment_means"][0]["payee_financial_account"] = {"id": required(invoice, "custom_addons_einv_bank_account", "Supplier payment account identifier")}
        if invoice.get("custom_addons_einv_bank_account_name"):
            payload["payment_means"][0]["payee_financial_account"]["name"] = invoice["custom_addons_einv_bank_account_name"]
    elif code not in {"1", "10", "20", "21", "68"}:
        raise MappingError("Purchase payment method needs additional mapping; use a supported actual payment method")
    if "delivery" in payload:
        if not invoice.get("_delivery_address"):
            raise MappingError("Select a company shipping address for the actual supply date")
        payload["delivery"]["delivery_location"] = {"address": invoice["_delivery_address"]}
    return payload, expected


def build(invoice, connection):
    import frappe
    from frappe.utils import get_system_timezone
    if not invoice.supplier_address:
        frappe.throw("Select the supplier billing address")
    supplier = frappe.get_doc("Supplier", invoice.supplier).as_dict()
    if supplier.get("custom_addons_einv_passport_country"):
        supplier["custom_addons_einv_passport_country_code"] = (frappe.db.get_value("Country", supplier["custom_addons_einv_passport_country"], "code") or "").upper()
    address = frappe.get_doc("Address", invoice.supplier_address).as_dict()
    country = frappe.db.get_value("Country", address.country, "code") or ""
    data = invoice.as_dict()
    if invoice.shipping_address:
        shipping = frappe.get_doc("Address", invoice.shipping_address)
        code = frappe.db.get_value("Country", shipping.country, "code") or ""
        region = shipping.get("custom_addons_einv_region")
        if not all((shipping.address_line1, shipping.city, region, code)):
            frappe.throw("Complete the company shipping address and emirate code")
        data["_delivery_address"] = {"street_name": shipping.address_line1, "city_name": shipping.city,
            "country_subentity": region, "country": shipping.country, "country_code": code.upper()}
    try:
        payload, expected = build_purchase_payload(data, supplier, address, country, connection.as_dict(), get_system_timezone())
        from addons_einvoicing.domain import canonical
        if len(canonical(payload).encode()) > 8 * 1024 * 1024:
            frappe.throw("Invoice JSON exceeds 8 MB")
        return payload, expected
    except (MappingError, ValueError) as exc:
        frappe.throw(str(exc))
