// Preserve ERPNext's existing list handlers.
(() => {
    const settings = frappe.listview_settings["Sales Invoice"] || {};
    const original = settings.onload;
    settings.onload = function(listview) {
        if (original) original.call(this, listview);
        if (!frappe.user_roles.some(r => ["System Manager", "Addons E Invoice Operator"].includes(r))) return;
        listview.page.add_action_item(__("Queue E-Invoices"), () => {
            const names = listview.get_checked_items().map(row => row.name);
            if (!names.length || names.length > 50) return frappe.msgprint(__("Select between 1 and 50 invoices."));
            frappe.confirm(__("Queue {0} selected invoices for e-invoicing?", [names.length]), async () => {
                const {message} = await frappe.call({method: "addons_einvoicing.api.queue_invoices", args: {sales_invoices: names}, freeze: true});
                frappe.msgprint(__("{0} e-invoice submissions queued or already recorded.", [message.length]));
                listview.refresh();
            });
        });
    };
    frappe.listview_settings["Sales Invoice"] = settings;
})();
