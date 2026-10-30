frappe.ui.form.on("Addons E Invoice Webhook Event", {
    refresh(frm) {
        if (frm.doc.status === "Error") frm.add_custom_button(__("Retry Processing"), async () => {
            await frappe.call({method: "addons_einvoicing.api.retry_webhook", args: {event: frm.doc.name}, freeze: true});
            await frm.reload_doc();
        });
    }
});
