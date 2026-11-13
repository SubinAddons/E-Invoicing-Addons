import unittest
from test_domain import fixture
from addons_einvoicing.purchase import build_purchase_payload
from addons_einvoicing.domain import MappingError
from addons_einvoicing.sources import source_reference, source_field
from types import SimpleNamespace

class PurchaseTests(unittest.TestCase):
    def fixture(self):
        f = fixture()
        f[0].update(custom_addons_einv_self_billing=1, custom_addons_einv_payment_code="1")
        f[1].update(supplier_name="Supplier", custom_addons_einv_registration_id="46920203", custom_addons_einv_registration_type="CD", custom_addons_einv_telephone="+971501234567")
        f[4]["provider"] = "ArdentaxIT"
        return f

    def test_roles_and_totals(self):
        f = self.fixture()
        p, expected = build_purchase_payload(*f)
        self.assertEqual(p["invoice_type_code"], "389")
        self.assertIn("accounting_supplier_party", p)
        self.assertNotIn("accounting_customer_party", p)
        self.assertEqual(expected["payable_amount"], 210)
        self.assertNotIn("custom_addons_einv_type_code", f[0])

    def test_guards(self):
        for field, value in [("custom_addons_einv_self_billing", 0), ("is_return", 1), ("custom_addons_einv_profile_execution_id", "01000000")]:
            f = self.fixture(); f[0][field] = value
            with self.assertRaises(MappingError): build_purchase_payload(*f)
        f = self.fixture(); f[1]["custom_addons_einv_telephone"] = ""
        with self.assertRaises(MappingError): build_purchase_payload(*f)
        f = self.fixture(); f[4]["provider"] = "Fynamics"
        with self.assertRaises(MappingError): build_purchase_payload(*f)

    def test_bank_transfer_requires_account(self):
        f = self.fixture(); f[0]["custom_addons_einv_payment_code"] = "30"
        with self.assertRaises(MappingError): build_purchase_payload(*f)
        f[0]["custom_addons_einv_bank_account"] = "TEST-ACCOUNT"
        p, _ = build_purchase_payload(*f)
        self.assertEqual(p["payment_means"][0]["payee_financial_account"]["id"], "TEST-ACCOUNT")

    def test_source_is_unambiguous(self):
        self.assertEqual(source_reference(SimpleNamespace(purchase_invoice="PINV-1")), ("Purchase Invoice", "PINV-1"))
        with self.assertRaises(ValueError): source_reference(SimpleNamespace(purchase_invoice="P", sales_invoice="S"))
        with self.assertRaises(ValueError): source_field("Supplier")

    def test_optional_registration_and_supplier_identifiers(self):
        f = self.fixture()
        f[1].update(custom_addons_einv_party_id="SUP-123", custom_addons_einv_party_scheme="0235")
        f[0].update(custom_addons_einv_buyer_reference="BUY-123", custom_addons_einv_note="Self-billing agreement")
        p, _ = build_purchase_payload(*f)
        self.assertEqual(p["accounting_supplier_party"]["party_identification_id"], "SUP-123")
        self.assertEqual(p["buyer_reference"], "BUY-123")
        self.assertEqual(p["accounting_supplier_party"]["company_id"], "46920203")

    def test_conditional_supplier_fields(self):
        for updates in [dict(custom_addons_einv_registration_type="TL"),
                        dict(custom_addons_einv_registration_type="TL", custom_addons_einv_registration_id="123"),
                        dict(custom_addons_einv_registration_type="PAS", custom_addons_einv_registration_id="123"),
                        dict(custom_addons_einv_party_scheme="0235"),
                        dict(custom_addons_einv_tin="invalid")]:
            f = self.fixture(); f[1].update(updates)
            with self.assertRaises(MappingError): build_purchase_payload(*f)
        f = self.fixture()
        f[1].update(custom_addons_einv_registration_type="PAS", custom_addons_einv_registration_id="123", custom_addons_einv_passport_country_code="AE")
        p, _ = build_purchase_payload(*f)
        self.assertEqual(p["accounting_supplier_party"]["passport_issuing_country_code"], "AE")

    def test_uae_supplier_registration_required(self):
        f = self.fixture(); f[1]["custom_addons_einv_registration_id"] = ""
        with self.assertRaisesRegex(MappingError, "registration ID"):
            build_purchase_payload(*f)
