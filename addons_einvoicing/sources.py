"""Strict source-document routing for shared sales and purchase jobs."""

def source_field(doctype):
    if doctype not in {"Sales Invoice", "Purchase Invoice"}:
        raise ValueError("Unsupported invoice type")
    return "purchase_invoice" if doctype == "Purchase Invoice" else "sales_invoice"


def source_reference(doc):
    purchase = getattr(doc, "purchase_invoice", None)
    sales = getattr(doc, "sales_invoice", None)
    if bool(purchase) == bool(sales):
        raise ValueError("Submission must link exactly one sales or purchase invoice")
    return ("Purchase Invoice", purchase) if purchase else ("Sales Invoice", sales)
