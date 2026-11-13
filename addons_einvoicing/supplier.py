"""Supplier master validation for the supported UAE purchase workflow."""
import re
from addons_einvoicing.domain import MappingError, required


def validate_fields(data):
    for field, label in (("legal_name", "Supplier legal name"), ("email", "Supplier email"),
                         ("telephone", "Supplier telephone"), ("tin", "Supplier UAE TIN"),
                         ("endpoint_id", "Supplier Peppol endpoint"), ("endpoint_scheme", "Supplier endpoint scheme")):
        required(data, "custom_addons_einv_" + field, label)
    if not re.fullmatch(r"1\d{9}", str(data.get("custom_addons_einv_tin") or "").strip()):
        raise MappingError("Supplier UAE TIN must be 10 digits starting with 1")
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", str(data.get("custom_addons_einv_email") or "").strip()):
        raise MappingError("Invalid supplier e-invoice email")
    if data.get("tax_id") and not re.fullmatch(r"1\d{12}03", str(data["tax_id"]).strip()):
        raise MappingError("Supplier VAT TRN must be 15 digits starting with 1 and ending with 03")
    if str(data.get("custom_addons_einv_endpoint_scheme") or "").strip() == "0235":
        required(data, "custom_addons_einv_registration_id", "Supplier legal registration ID for Peppol scheme 0235")
        required(data, "custom_addons_einv_registration_type", "Supplier registration type for Peppol scheme 0235")
    kind = data.get("custom_addons_einv_registration_type")
    if bool(kind) != bool(data.get("custom_addons_einv_registration_id")):
        raise MappingError("Supplier registration ID and type must be supplied together")
    if kind == "TL":
        required(data, "custom_addons_einv_registration_authority", "Supplier registration issuing authority")
    if kind == "PAS":
        required(data, "custom_addons_einv_passport_country_code", "Supplier passport issuing country ISO code")
    if data.get("custom_addons_einv_party_scheme"):
        required(data, "custom_addons_einv_party_id", "Supplier party identification")
        if not re.fullmatch(r"\d{4}", str(data["custom_addons_einv_party_scheme"])):
            raise MappingError("Supplier party identification scheme must be a four-digit ISO 6523 ICD code")


def validate(doc, method=None):
    if not doc.get("custom_addons_einv_enabled"):
        return
    import frappe
    data = doc.as_dict()
    if data.get("custom_addons_einv_passport_country"):
        data["custom_addons_einv_passport_country_code"] = (frappe.db.get_value("Country", data["custom_addons_einv_passport_country"], "code") or "").upper()
    try:
        validate_fields(data)
    except MappingError as exc:
        frappe.throw(str(exc))
