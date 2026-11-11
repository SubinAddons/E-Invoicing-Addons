import copy
import unittest
from addons_einvoicing.domain import build_payload, MappingError, signature, verify_signature, reconcile, processing_state

def fixture():
    invoice = dict(name='INV-0001', company='Test Company', customer='Buyer', posting_date='2026-10-16', posting_time='10:30:00', due_date='2026-11-16', currency='AED', net_total=200, total_taxes_and_charges=10, grand_total=210, rounded_total=210, custom_addons_einv_payment_code='30', items=[dict(item_code='SVC', item_name='Service', qty=2, net_amount=200, uom='Nos')], taxes=[dict(charge_type='On Net Total', rate=5, account_head='VAT')])
    customer = dict(customer_type='Company', customer_name='Buyer', custom_addons_einv_legal_name='Buyer LLC', custom_addons_einv_email='billing@example.test', custom_addons_einv_tin='1000000001', tax_id='100000000000003', custom_addons_einv_endpoint_id='1000000001', custom_addons_einv_endpoint_scheme='0235')
    address = dict(address_line1='Street', city='Dubai', country='United Arab Emirates', custom_addons_einv_region='DXB')
    config = dict(tax_mappings=[dict(category='S', rate=5)], uom_mappings=[dict(uom='Nos', unit_code='EA')], credit_notes_verified=1)
    return invoice, customer, address, 'AE', config, 'Asia/Dubai'

class MappingTests(unittest.TestCase):
    def test_standard_payload(self):
        p,e=build_payload(*fixture())
        self.assertEqual(p['document_lines'][0]['price']['base_amount'],100)
        self.assertEqual(p['document_lines'][0]['description'],'Service')
        self.assertEqual(p['payment_means'],[{'payment_means_code':'30'}])
        self.assertEqual(e['payable_amount'],210)
        self.assertNotIn('accounting_supplier_party',p)
        self.assertNotIn('tax_amount',p)
    def test_buyer_registration_and_full_endpoint(self):
        f=fixture();f[1].update(custom_addons_einv_registration_id='12345678',custom_addons_einv_registration_type='CD',custom_addons_einv_telephone='+971501234567',custom_addons_einv_endpoint_id='0235:1000000001')
        p,_=build_payload(*f);b=p['accounting_customer_party']
        self.assertEqual(b['endpoint_id'],'1000000001')
        self.assertEqual(b['company_id'],'12345678')
        self.assertEqual(b['scheme_agency_id'],'CD')
        self.assertEqual(b['telephone'],'+971501234567')
    def test_registration_pair_required(self):
        f=fixture();f[1]['custom_addons_einv_registration_id']='12345678'
        with self.assertRaisesRegex(MappingError,'together'):build_payload(*f)
    def test_endpoint_scheme_mismatch(self):
        f=fixture();f[1]['custom_addons_einv_endpoint_id']='9999:1000000001'
        with self.assertRaisesRegex(MappingError,'scheme'):build_payload(*f)
    def test_deemed_supply_endpoint_is_scenario_specific(self):
        f=fixture();f[0]['custom_addons_einv_profile_execution_id']='01000000'
        p,_=build_payload(*f)
        self.assertEqual(p['accounting_customer_party']['endpoint_id'],'9900000097')
        self.assertEqual(f[1]['custom_addons_einv_endpoint_id'],'1000000001')
        f[0]['custom_addons_einv_profile_execution_id']='00000000'
        p,_=build_payload(*f);self.assertEqual(p['accounting_customer_party']['endpoint_id'],'1000000001')
    def test_deemed_supply_provider_and_production_guards(self):
        f=fixture();f[0]['custom_addons_einv_profile_execution_id']='01000000';f[4]['provider']='Fynamics'
        with self.assertRaisesRegex(MappingError,'ArdentaxIT'):build_payload(*f)
        f[4].update(provider='ArdentaxIT',environment='Production')
        with self.assertRaisesRegex(MappingError,'verification'):build_payload(*f)
    def test_standard_cannot_use_deemed_endpoint(self):
        f=fixture();f[1]['custom_addons_einv_endpoint_id']='9900000097'
        with self.assertRaisesRegex(MappingError,'Substitute'):build_payload(*f)
    def test_timezone_rolls_date(self):
        f=list(fixture());f[0]['posting_time']='00:30:00';f[-1]='Asia/Kolkata'
        p,_=build_payload(*f)
        self.assertEqual((p['issue_date'],p['issue_time']),('2026-10-15','23:00:00'))
    def test_missing_tin(self):
        f=fixture();f[1]['custom_addons_einv_tin']=''
        with self.assertRaisesRegex(MappingError,'TIN'):build_payload(*f)
    def test_trn_not_tin(self):
        f=fixture();f[1]['custom_addons_einv_tin']=f[1]['tax_id']
        with self.assertRaisesRegex(MappingError,'10 digits'):build_payload(*f)
    def test_no_master_uom_fallback(self):
        f=fixture();f[4]['uom_mappings']=[]
        with self.assertRaisesRegex(MappingError,'UOM'):build_payload(*f)
    def test_item_tax_mismatch(self):
        f=fixture();f[0]['items'][0]['item_tax_rate']='{"VAT":0}'
        with self.assertRaisesRegex(MappingError,'mapped rate'):build_payload(*f)
    def test_net_discount_not_doubled(self):
        f=fixture();i=f[0];i.update(discount_amount=20,apply_discount_on='Net Total',net_total=180,total_taxes_and_charges=9,grand_total=189,rounded_total=189);i['items'][0]['net_amount']=180
        p,e=build_payload(*f);self.assertNotIn('allowances',p);self.assertEqual(e['payable_amount'],189)
    def test_compound_tax_rejected(self):
        f=fixture();f[0]['taxes'].append(dict(charge_type='Actual',tax_amount=5))
        with self.assertRaisesRegex(MappingError,'VAT row'):build_payload(*f)
    def test_prepaid_rejected(self):
        f=fixture();f[0]['total_advance']=10
        with self.assertRaisesRegex(MappingError,'prepayments'):build_payload(*f)
    def test_non_aed_requires_explicit_rate(self):
        f=fixture();f[0]['currency']='USD'
        with self.assertRaisesRegex(MappingError,'Exchange Rate'):build_payload(*f)
        f[0]['custom_addons_einv_aed_rate']=3.6725
        p,_=build_payload(*f);self.assertEqual(p['tax_exchange_rate']['target_currency_code'],'AED')
    def test_credit_note_normalizes_sign_once(self):
        f=fixture();original=copy.deepcopy(f[0]);f[0].update(name='CN-1',is_return=1,return_against=original['name'],custom_addons_einv_discrepancy='DL8.61.1.A',net_total=-200,total_taxes_and_charges=-10,grand_total=-210,rounded_total=-210);f[0]['items'][0].update(qty=-2,net_amount=-200)
        p,_=build_payload(*f,original=original)
        self.assertEqual(p['document_lines'][0]['quantity'],2)
        self.assertEqual(p['credit_note_type_code'],'381')
        self.assertEqual(p['billing_reference'][0]['id'],'INV-0001')
        self.assertNotIn('payment_means',p)
    def test_unverified_credit_note_blocked(self):
        f=fixture();original=copy.deepcopy(f[0]);f[4]['credit_notes_verified']=0;f[0].update(is_return=1,return_against=original['name']);f[0]['items'][0].update(qty=-2,net_amount=-200)
        with self.assertRaisesRegex(MappingError,'Confirm credit'):build_payload(*f,original=original)
    def test_export_delivery_required(self):
        f=list(fixture());f[0]['custom_addons_einv_profile_execution_id']='00000001';f[3]='GB';f[2].update(country='United Kingdom',custom_addons_einv_region='London')
        with self.assertRaisesRegex(MappingError,'shipping'):build_payload(*f)
        f[0]['_delivery_address']=dict(street_name='Road',city_name='London',country='United Kingdom',country_code='GB',country_subentity='London')
        p,_=build_payload(*f);self.assertNotIn('tin',p['accounting_customer_party']);self.assertNotIn('party_tax_scheme',p['accounting_customer_party'])
    def test_exempt_requires_reason_code(self):
        f=fixture();f[0].update(custom_addons_einv_type_code='480',total_taxes_and_charges=0,grand_total=200,rounded_total=200);f[0]['taxes']=[];f[4]['tax_mappings']=[dict(category='E',rate=0,exemption_reason='Reason')]
        with self.assertRaisesRegex(MappingError,'reason code'):build_payload(*f)
    def test_nan_rejected(self):
        f=fixture();f[0]['items'][0]['net_amount']=float('nan')
        with self.assertRaisesRegex(MappingError,'Non-finite'):build_payload(*f)
    def test_mismatch_detected(self):
        self.assertTrue(reconcile(dict(tax_amount=10.01),dict(tax_amount=10)))
        self.assertTrue(reconcile({},dict(tax_amount=10)))
    def test_no_http_success_assumption(self):
        self.assertEqual(processing_state({'id':'abc'})[0],'Created')
        self.assertEqual(processing_state({'meta_info':{'peppol_status':{'overall_status':'APPROVED'}}})[0],'Approved')
    def test_signature_raw_bytes(self):
        raw=b'{"a":1}';s=signature('secret',raw)
        self.assertTrue(verify_signature('secret',raw,s))
        self.assertFalse(verify_signature('secret',b'{"a": 1}',s))
        self.assertFalse(verify_signature('',raw,s))

if __name__=='__main__': unittest.main()
