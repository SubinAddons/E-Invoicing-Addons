// Preserve ERPNext's existing list handlers.
(() => {
    const settings = frappe.listview_settings["Sales Invoice"] || {};
    // UUID is maintained server-side only for the latest approved submission.
    settings.add_fields = [...new Set([...(settings.add_fields || []), "custom_addons_einv_uuid"])];
    const originalRefresh = settings.refresh;
    settings.refresh = function(listview) {
        if (originalRefresh) originalRefresh.call(this, listview);
        const invoices = new Map(listview.data.map(doc => [doc.name, doc]));
        listview.$result.find(".list-row-container").each(function() {
            const row = $(this);
            const subject = row.find(".list-subject").first();
            subject.find(".addons-einvoice-list-dot").remove();
            const encodedName = row.find(".list-row-checkbox").attr("data-name");
            if (!encodedName) return;
            const doc = invoices.get(encodedName) || invoices.get(decodeURIComponent(encodedName));
            if (!doc) return;
            if (!doc.custom_addons_einv_uuid) return;
            const label = __("E-Invoice: Approved");
            $("<span>", {
                class: "addons-einvoice-list-dot", role: "img",
                "aria-label": label, title: label, tabindex: "0"
            }).css({
                display: "inline-block", width: "12px", height: "12px",
                "min-width": "12px", "border-radius": "50%", "flex-shrink": "0",
                "margin-left": "8px", "margin-right": "8px",
                "background-color": "#16a34a"
            }).appendTo(subject);
        });
    };
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
