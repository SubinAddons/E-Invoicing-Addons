frappe.ui.form.on("Addons E Invoice Settings", {
    provider(frm) {
        const origins = {ArdentaxIT: "https://api-sandbox.ae.ardentaxit.tax", Fynamics: "https://sandbox-uae.fynamicstax.com"};
        frm.set_value("enabled", 0);
        frm.set_value("production_verified", 0);
        frm.set_value("credit_notes_verified", 0);
        frm.set_value("environment", "Sandbox");
        frm.set_value("api_base_url", origins[frm.doc.provider]);
        frm.set_value("client_id", "");
        frm.set_value("client_secret", "");
        frm.set_value("webhook_secret", "");
        frm.set_value("previous_webhook_secret", "");
    },
    environment(frm) {
        if (frm.doc.provider === "Fynamics") frm.set_value("api_base_url", frm.doc.environment === "Production" ? "https://uae.fynamicstax.com" : "https://sandbox-uae.fynamicstax.com");
    },
    refresh(frm) {
        if (!frm.is_new()) frm.add_custom_button(__("Test Authentication"), async () => {
            if (frm.is_dirty()) return frappe.msgprint(__("Save settings first."));
            const {message} = await frappe.call({method: "addons_einvoicing.api.test_connection", args: {connection: frm.doc.name}, freeze: true});
            frappe.msgprint(__("Authentication succeeded in {0}. No invoice was submitted.", [message.environment]));
        });
    }
});
