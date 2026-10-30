frappe.ui.form.on("Sales Invoice", {
    refresh(frm) {
        if (frm.is_new() || !frappe.user_roles.some(r => ["System Manager", "Addons E Invoice Operator"].includes(r))) return;
        frappe.call({method: "addons_einvoicing.api.invoice_status", args: {sales_invoice: frm.doc.name}}).then(({message}) => {
            if (message && message.length) {
                const latest = message[0];
                const color = latest.status === "Approved" ? "green" : ["Error", "Unknown", "Mismatch", "Rejected", "Validation Failed"].includes(latest.status) ? "red" : "orange";
                frm.dashboard.add_indicator(__("E-Invoice: {0} ({1})", [latest.status, latest.environment]), color);
            }
        });
        frm.add_custom_button(__("Validate / Preview"), async () => {
            if (frm.is_dirty()) return frappe.msgprint(__("Save the invoice before previewing."));
            const {message} = await frappe.call({method: "addons_einvoicing.api.preview", args: {sales_invoice: frm.doc.name}, freeze: true});
            const d = new frappe.ui.Dialog({title: __("E-Invoice Preview — {0}", [message.environment]), size: "large",
                fields: [{fieldname: "preview", fieldtype: "Code", options: "JSON", read_only: 1}]});
            d.set_value("preview", JSON.stringify(message, null, 2)); d.show();
        }, __("E-Invoice"));
        if (frm.doc.docstatus === 1) frm.add_custom_button(__("Queue Submission"), async () => {
            if (frm.is_dirty()) return frappe.msgprint(__("Save the invoice first."));
            const {message} = await frappe.call({method: "addons_einvoicing.api.queue_invoice", args: {sales_invoice: frm.doc.name}, freeze: true});
            frappe.set_route("Form", "Addons E Invoice Submission", message);
        }, __("E-Invoice"));
        frm.add_custom_button(__("View Submissions"), () => frappe.set_route("List", "Addons E Invoice Submission", {sales_invoice: frm.doc.name}), __("E-Invoice"));
    }
});
