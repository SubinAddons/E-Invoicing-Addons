import copy
import hashlib
import hmac
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import requests
from test_client import Cache, response
from test_domain import fixture
from addons_einvoicing.domain import build_payload, MappingError
from addons_einvoicing.client import APIError
from addons_einvoicing.fynamics import Client, BASES, CREATE, STATUS, map_payload, state, verify_signature, artifact_path, validate_base_url

UUID='123e4567-e89b-12d3-a456-426614174000'

def client():
    config=SimpleNamespace(api_base_url=BASES['Sandbox'],environment='Sandbox',client_id='client',get_password=lambda f:'secret')
    session=Mock();c=Client(config,Cache(),session);c.cache.set_value(c.token_key,'token');return c,session

class FynamicsTests(unittest.TestCase):
    def test_oauth_form_and_cache(self):
        c,s=client();c.cache.delete_value(c.token_key)
        s.request.return_value=response(data={'success':1,'data':{'access_token':'new','token_type':'Bearer','expires_in':3600}})
        self.assertEqual(c.token(),'new');self.assertEqual(c.token(),'new')
        self.assertEqual(s.request.call_count,1)
        kw=s.request.call_args.kwargs
        self.assertEqual(kw['data'],{'grant_type':'client_credentials'})
        self.assertEqual(kw['headers']['Authorization'],'Basic Y2xpZW50OnNlY3JldA==')
        self.assertFalse(kw['allow_redirects'])

    def test_auth_failure_not_invoice_uncertainty(self):
        c,s=client();c.cache.delete_value(c.token_key);s.request.side_effect=requests.Timeout('secret')
        with self.assertRaises(APIError) as exc:c.token()
        self.assertFalse(exc.exception.uncertain);self.assertNotIn('secret',str(exc.exception))

    def test_timeout_unknown_no_replay(self):
        c,s=client();s.request.side_effect=requests.Timeout('secret')
        with self.assertRaises(APIError) as exc:c.request('POST',CREATE,{})
        self.assertTrue(exc.exception.uncertain);self.assertEqual(s.request.call_count,1)

    def test_duplicate_409_unknown(self):
        c,s=client();s.request.return_value=response(409)
        with self.assertRaises(APIError) as exc:c.request('POST',CREATE,{})
        self.assertTrue(exc.exception.uncertain)

    def test_one_refresh_on_401(self):
        c,s=client();s.request.side_effect=[response(401),response(data={'success':1,'data':{'access_token':'new','token_type':'Bearer','expires_in':3600}}),response(data={'uuid':UUID})]
        self.assertEqual(c.request('POST',CREATE,{})['uuid'],UUID);self.assertEqual(s.request.call_count,3)

    def test_map_amounts_no_duplicate_discount(self):
        f=fixture();f[0].update(discount_amount=20,apply_discount_on='Net Total',net_total=180,total_taxes_and_charges=9,grand_total=189,rounded_total=189);f[0]['items'][0]['net_amount']=180
        p,e=build_payload(*f);out=map_payload(p,e,{'PartyName':'Supplier'})
        self.assertEqual(out['Invoice']['InvoiceNumber'],f[0]['name'])
        self.assertEqual(out['InvoiceLine'][0]['Price']['PriceAmount'],90)
        self.assertEqual(out['LegalMonetaryTotal']['PayableAmount'],189)
        self.assertNotIn('TotalAllowance',out)
        self.assertEqual(out['TaxTotal']['DocumentTaxSubtotal'][0]['TaxAmount'],9)

    def test_scope_rejects_foreign_currency(self):
        p,e=build_payload(*fixture());p['document_currency_code']='USD'
        with self.assertRaises(MappingError):map_payload(p,e,{})

    def test_credit_reference(self):
        f=fixture();orig=copy.deepcopy(f[0]);f[0].update(name='CN1',is_return=1,return_against=orig['name'],custom_addons_einv_discrepancy='VD',net_total=-200,total_taxes_and_charges=-10,grand_total=-210,rounded_total=-210);f[0]['items'][0].update(qty=-2,net_amount=-200)
        p,e=build_payload(*f,original=orig);out=map_payload(p,e,{})
        self.assertEqual(out['Invoice']['InvoiceTypeCode'],'381');self.assertEqual(out['InvoiceLine'][0]['InvoicedQuantity'],2)
        self.assertEqual(out['BillingReference'][0]['ID'],orig['name'])

    def test_approval_needs_both_acks(self):
        p={'messageUuid':UUID,'documentStatus':'SUCCESS','to_c3':{'mls':{'responseCode':'AP'}},'to_c5':{}}
        self.assertEqual(state(p,UUID)[0],'Processing')
        p['to_c5']['mls']={'responseCode':'AP'};self.assertEqual(state(p,UUID)[0],'Approved')
        p['to_c3']['mls']['responseCode']='RE';self.assertEqual(state(p,UUID)[0],'Rejected')
        with self.assertRaises(ValueError):state(p,'00000000-0000-4000-8000-000000000002')

    def test_signature_exact_bytes(self):
        raw=b'{"messageUuid":"a"}';sig='sha256='+hmac.new(b'secret',raw,hashlib.sha256).hexdigest()
        self.assertTrue(verify_signature('secret',raw,sig));self.assertFalse(verify_signature('secret',raw+b' ',sig))
        self.assertFalse(verify_signature('',raw,sig))

    def test_download_origin_path_and_redirect_protection(self):
        base=BASES['Sandbox'];path='/api/partner/sales-invoice/print-from-url/abc_DEF='
        self.assertEqual(artifact_path(base+path,base,'pdf'),path)
        for bad in ['https://evil.test'+path,base+'/api/partner/auth/authenticate',base+path+'?x=y',base+path+'/../foo',base+path+'%2fsecret']:
            with self.assertRaises(ValueError):artifact_path(bad,base,'pdf')
        with self.assertRaises(ValueError):validate_base_url('https://uae.fynamicstax.com','Sandbox')
        c,s=client();s.request.return_value=response(302)
        with self.assertRaises(APIError):c.request('GET',STATUS+UUID)
        self.assertFalse(s.request.call_args.kwargs['allow_redirects'])
