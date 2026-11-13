// Preserve ERPNext's existing list handlers.
(() => {
    const settings = frappe.listview_settings["Purchase Invoice"] || {};
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
            // Reserve space for the marker even when the supplier title is long.
            subject.css({display: "flex", "align-items": "center", "justify-content": "flex-start"});
            subject.children(".select-like").css({"flex-shrink": "0"});
            subject.find("a[data-doctype]").first().parent().css({"min-width": "0", "flex": "0 1 auto", "overflow": "hidden"});
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
    frappe.listview_settings["Purchase Invoice"] = settings;
})();
