// Keep the approval marker beside the E-Invoice menu, independent of payment status.
function addons_purchase_einvoice_status_dot(frm, status) {
    const group = frm.page.get_inner_group_button(__("E-Invoice"));
    frm.page.inner_toolbar.find(".addons-einvoice-status-dot").remove();
    if (!group.length) return;
    const label = __("E-Invoice: {0}", [__(status)]);
    $("<span>", {
        class: "addons-einvoice-status-dot",
        role: "img",
        "aria-label": label,
        title: label,
        tabindex: "0"
    }).css({
        display: "inline-block", width: "12px", height: "12px",
        "border-radius": "50%", "flex-shrink": "0",
        "background-color": status === "Approved" ? "#16a34a" : "#dc2626",
        "align-self": "center", "margin-left": "12px", "margin-right": "8px"
    }).insertBefore(group);
}

frappe.ui.form.on("Purchase Invoice", {
    refresh(frm) {
        if (frm.is_new() || !frappe.user_roles.some(r => ["System Manager", "Addons E Invoice Operator"].includes(r))) return;
        const requestId = frm.__addons_status_request = (frm.__addons_status_request || 0) + 1;
        frappe.call({method: "addons_einvoicing.api.invoice_status", args: {sales_invoice: frm.doc.name, doctype: "Purchase Invoice"}}).then(({message}) => {
            if (requestId !== frm.__addons_status_request) return;
            addons_purchase_einvoice_status_dot(frm, message && message.length ? message[0].status : "Not submitted");
            if (message && message.length) {
                const latest = message[0];
                frm.doc.custom_addons_einv_uuid = latest.status === "Approved" ? latest.provider_uuid : "";
                frm.refresh_field("custom_addons_einv_uuid");
                if (latest.status === "Approved" && latest.provider_uuid && latest.provider === "ArdentaxIT" && frm.doc.docstatus === 1) {
                    frm.add_custom_button(__("Download Approved PDF"), async () => {
                        const {message: result} = await frappe.call({
                            method: "addons_einvoicing.api.download_invoice_pdf",
                            args: {sales_invoice: frm.doc.name, doctype: "Purchase Invoice"}, freeze: true,
                            freeze_message: __("Fetching approved invoice PDF…")
                        });
                        if (result && result.pdf_file) {
                            const link = document.createElement("a");
                            link.href = result.pdf_file;
                            link.download = "";
                            document.body.appendChild(link);
                            link.click();
                            link.remove();
                        }
                    }, __("E-Invoice"));
                }
                const color = latest.status === "Approved" ? "green" : "red";
                frm.dashboard.add_indicator(__("E-Invoice: {0} ({1})", [latest.status, latest.environment]), color);
            }
        }).catch(() => {
            if (requestId === frm.__addons_status_request) addons_purchase_einvoice_status_dot(frm, "Status unavailable");
        });
        frm.add_custom_button(__("Validate / Preview"), async () => {
            if (frm.is_dirty()) return frappe.msgprint(__("Save the invoice before previewing."));
            const {message} = await frappe.call({method: "addons_einvoicing.api.preview", args: {sales_invoice: frm.doc.name, doctype: "Purchase Invoice"}, freeze: true});
            const d = new frappe.ui.Dialog({title: __("E-Invoice Preview — {0}", [message.environment]), size: "large",
                fields: [{fieldname: "preview", fieldtype: "Code", options: "JSON", read_only: 1}]});
            d.set_value("preview", JSON.stringify(message, null, 2)); d.show();
        }, __("E-Invoice"));
        if (frm.doc.docstatus === 1) frm.add_custom_button(__("Queue Submission"), async () => {
            if (frm.is_dirty()) return frappe.msgprint(__("Save the invoice first."));
            const {message} = await frappe.call({method: "addons_einvoicing.api.queue_invoice", args: {sales_invoice: frm.doc.name, doctype: "Purchase Invoice"}, freeze: true});
            frappe.set_route("Form", "Addons E Invoice Submission", message);
        }, __("E-Invoice"));
        frm.add_custom_button(__("View Submissions"), () => frappe.set_route("List", "Addons E Invoice Submission", {purchase_invoice: frm.doc.name}), __("E-Invoice"));
        addons_purchase_einvoice_status_dot(frm, "Checking status");
    }
});
