app_name = "addons_einvoicing"
app_title = "Addons - E invoicing"
app_publisher = "Addons Technologies"
app_description = "UAE e-invoicing through ArdentaxIT and Fynamics"
app_email = ""
app_license = "MIT"
required_apps = ["erpnext"]
after_install = "addons_einvoicing.install.setup"
after_migrate = "addons_einvoicing.install.setup"
doctype_js = {"Sales Invoice": "public/js/sales_invoice.js"}
doc_events = {
    "Customer": {"validate": "addons_einvoicing.customer.validate"},
    "Sales Invoice": {
        "before_submit": "addons_einvoicing.events.before_submit",
        "on_submit": "addons_einvoicing.events.on_submit",
        "before_cancel": "addons_einvoicing.events.before_cancel",
    },
}
scheduler_events = {"cron": {"*/5 * * * *": ["addons_einvoicing.jobs.recover"]}}
permission_query_conditions = {
    name: "addons_einvoicing.permissions.query_conditions"
    for name in ("Addons E Invoice Submission", "Addons E Invoice Webhook Event", "Addons E Invoice Inbox", "Addons E Invoice Audit")
}
has_permission = {
    name: "addons_einvoicing.permissions.has_permission"
    for name in ("Addons E Invoice Submission", "Addons E Invoice Webhook Event", "Addons E Invoice Inbox", "Addons E Invoice Audit")
}

doctype_list_js = {"Sales Invoice": "public/js/sales_invoice_list.js"}
