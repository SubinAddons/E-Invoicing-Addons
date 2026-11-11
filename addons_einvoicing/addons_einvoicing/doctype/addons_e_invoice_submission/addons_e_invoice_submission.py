from addons_einvoicing.controllers import ProtectedRecord


class AddonsEInvoiceSubmission(ProtectedRecord):
    def on_update(self):
        from addons_einvoicing.invoice_output import sync_invoice_uuid
        if self.sales_invoice:
            sync_invoice_uuid(self.sales_invoice)
