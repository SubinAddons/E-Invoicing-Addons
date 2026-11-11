import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
import sys


class InvoiceOutputTests(TestCase):
    def sync(self, rows):
        frappe = SimpleNamespace(get_all=Mock(return_value=rows), db=SimpleNamespace(set_value=Mock()))
        spec = importlib.util.spec_from_file_location('invoice_output_test', Path(__file__).parents[1] / 'addons_einvoicing/invoice_output.py')
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'frappe': frappe}):
            spec.loader.exec_module(module)
            module.sync_invoice_uuid('INV-1')
        return frappe

    def test_approved_uuid_is_persisted_without_changing_accounting_timestamp(self):
        f = self.sync([SimpleNamespace(status='Approved', provider_uuid='remote-id')])
        f.db.set_value.assert_called_once_with('Sales Invoice', 'INV-1', 'custom_addons_einv_uuid', 'remote-id', update_modified=False)
        self.assertEqual(f.get_all.call_args.kwargs['limit_page_length'], 1)

    def test_nonapproved_latest_clears_previous_uuid(self):
        for state in ['Mismatch', 'Rejected', 'Processing', 'Error', 'Unknown']:
            with self.subTest(state=state):
                f = self.sync([SimpleNamespace(status=state, provider_uuid='remote-id')])
                self.assertEqual(f.db.set_value.call_args.args[3], '')

    def test_no_submission_has_no_uuid(self):
        self.assertEqual(self.sync([]).db.set_value.call_args.args[3], '')
