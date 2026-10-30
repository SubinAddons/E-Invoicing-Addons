frappe.ui.form.on("Addons E Invoice Submission", {
    refresh(frm) {
        if (frm.is_new()) return;
        const call = async method => {
            await frappe.call({method: `addons_einvoicing.api.${method}`, args: {submission: frm.doc.name}, freeze: true});
            await frm.reload_doc();
            if (method !== "download_artifacts") frappe.show_alert({message: __("Job queued. Refresh this record after processing."), indicator: "blue"});
        };
        frm.add_custom_button(__("Refresh / Reconcile"), () => call("refresh_status"));
        if (["Error", "Validation Failed"].includes(frm.doc.status)) frm.add_custom_button(__("Rebuild and Retry"), () => call("correct_and_retry"));
        if (frm.doc.provider_uuid) frm.add_custom_button(__(frm.doc.provider === "Fynamics" ? "Fetch PDF and Compliance Files" : "Fetch PDF and XML"), () => call("download_artifacts"));
        if (frm.doc.provider !== "Fynamics" && frm.doc.status === "Unknown" && !frm.doc.provider_uuid) frm.add_custom_button(__("Link Existing Provider UUID"), () => {
            frappe.prompt([{fieldname: "provider_uuid", label: __("Provider UUID"), fieldtype: "Data", reqd: 1}], async values => {
                await frappe.call({method: "addons_einvoicing.api.link_existing", args: {submission: frm.doc.name, provider_uuid: values.provider_uuid}, freeze: true});
                await frm.reload_doc();
            }, __("Verify and link an existing document"));
        });
        frm.add_custom_button(__("Audit Trail"), () => frappe.set_route("List", "Addons E Invoice Audit", {submission: frm.doc.name}));
        if (frm.doc.status === "Unknown") frm.dashboard.set_headline_alert(__("Submission outcome is unknown. Reconciliation is read-only and will never create a duplicate invoice."));
    }
});
