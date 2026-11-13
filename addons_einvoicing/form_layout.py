"""Native Frappe sections and columns with explicit, repeatable field ordering."""
PREFIX = "custom_addons_einv_"


def arrange(fields, standard_fields):
    by_name = {f["fieldname"].removeprefix(PREFIX): f for f in fields}
    purchase = "self_billing" in by_name
    master = "legal_name" in by_name
    # Insert after the first standard section, without splitting its existing columns.
    anchor = standard_fields[0].fieldname
    for field in standard_fields[1:]:
        if field.fieldtype in {"Section Break", "Tab Break"}:
            break
        anchor = field.fieldname
    result = []

    def add(key, label=None, fieldtype=None):
        nonlocal anchor
        field = by_name[key] if key in by_name else {"fieldname": PREFIX + key, "fieldtype": fieldtype, "label": label or ""}
        if label is not None:
            field["label"] = label
        field["insert_after"] = anchor
        result.append(field)
        anchor = field["fieldname"]

    add("section", "E-Invoicing Details")
    if master:
        for key in ("enabled", "legal_name", "tin"): add(key)
        add("details_column", "", "Column Break")
        for key in ("email", "telephone"): add(key)
        add("registration_section", "Registration and Peppol", "Section Break")
        for key in ("registration_id", "registration_type", "registration_authority"): add(key)
        add("registration_column", "", "Column Break")
        for key in ("endpoint_id", "endpoint_scheme"): add(key)
        if "passport_country" in by_name: add("passport_country")
        if "party_id" in by_name:
            add("identification_section", "Additional Identification", "Section Break")
            add("party_id")
            add("identification_column", "", "Column Break")
            add("party_scheme")
    else:
        for key in ("enabled", "type_code", "profile_execution_id"): add(key)
        if purchase: add("self_billing")
        add("details_column", "", "Column Break")
        for key in ("payment_code", "supply_date", "aed_rate", "discrepancy"): add(key)
        if purchase:
            add("payment_section", "Payment Account and Reference", "Section Break")
            add("bank_account")
            add("bank_account_name")
            add("payment_column", "", "Column Break")
            add("buyer_reference")
        add("approval_section", "E-Invoice Reference", "Section Break")
        result[-1]["depends_on"] = "eval:doc.custom_addons_einv_uuid" if not purchase else ""
        add("uuid")
        if purchase: add("note")
    assert set(by_name) <= {f["fieldname"].removeprefix(PREFIX) for f in result}
    return result
