import frappe


def query_conditions(user=None):
    user = user or frappe.session.user
    if user == "Administrator":
        return ""
    from frappe.permissions import get_user_permissions
    companies = get_user_permissions(user).get("Company", [])
    if companies:
        allowed = ", ".join(frappe.db.escape(c["doc"]) for c in companies)
        return f"company in ({allowed})"
    return ""


def has_permission(doc, user=None, ptype=None):
    user = user or frappe.session.user
    if doc.company and not frappe.has_permission("Company", "read", doc=doc.company, user=user):
        return False
    if doc.doctype == "Addons E Invoice Submission" and doc.sales_invoice:
        if not frappe.has_permission("Sales Invoice", "read", doc=doc.sales_invoice, user=user):
            return False
    if doc.doctype == "Addons E Invoice Audit" and doc.submission:
        if not frappe.has_permission("Addons E Invoice Submission", "read", doc=doc.submission, user=user):
            return False
    # None leaves the standard role/DocType checks in effect.
    return None


def require_operator(invoice):
    if not set(frappe.get_roles()) & {"System Manager", "Addons E Invoice Operator"}:
        frappe.throw("Addons E Invoice Operator role required", frappe.PermissionError)
    invoice.check_permission("read")
    invoice.check_permission("submit")

