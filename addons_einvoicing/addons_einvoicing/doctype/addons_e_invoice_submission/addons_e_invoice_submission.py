from addons_einvoicing.controllers import ProtectedRecord
from addons_einvoicing.sources import source_reference


class AddonsEInvoiceSubmission(ProtectedRecord):
    def validate(self):
        super().validate()
        source_reference(self)

    def on_update(self):
        from addons_einvoicing.invoice_output import sync_invoice_uuid
        doctype, name = source_reference(self)
        sync_invoice_uuid(name, doctype)
