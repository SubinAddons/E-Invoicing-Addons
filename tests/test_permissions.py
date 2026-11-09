import importlib.util
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch


class PermissionTests(unittest.TestCase):
    def check(self, doctype, answers, **links):
        frappe = SimpleNamespace(session=SimpleNamespace(user="operator"), has_permission=Mock(side_effect=answers))
        path = Path(__file__).parents[1] / "addons_einvoicing" / "permissions.py"
        spec = importlib.util.spec_from_file_location("permission_test_module", path)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"frappe": frappe}):
            spec.loader.exec_module(module)
            return module.has_permission(SimpleNamespace(doctype=doctype, company="A", **links), ptype="read")

    def test_authorized_submission_explicitly_passes(self):
        self.assertIs(self.check("Addons E Invoice Submission", [True, True], sales_invoice="INV-1"), True)

    def test_company_denial_preserved(self):
        self.assertIs(self.check("Addons E Invoice Submission", [False], sales_invoice="INV-1"), False)

    def test_invoice_denial_preserved(self):
        self.assertIs(self.check("Addons E Invoice Submission", [True, False], sales_invoice="INV-1"), False)

    def test_audit_requires_submission_access(self):
        self.assertIs(self.check("Addons E Invoice Audit", [True, False], submission="SUB-1"), False)

    def test_other_protected_document_passes(self):
        self.assertIs(self.check("Addons E Invoice Inbox", [True]), True)
