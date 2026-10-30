import json
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock
import requests
from addons_einvoicing.client import Client,APIError,validate_base_url,SANDBOX

class Cache:
    def __init__(self):self.values={}
    def get_value(self,k):return self.values.get(k)
    def set_value(self,k,v,**kw):self.values[k]=v
    def delete_value(self,k):self.values.pop(k,None)
    def lock(self,*a,**kw):return nullcontext()

def response(code=200,data=None):
    r=Mock();r.__enter__=Mock(return_value=r);r.__exit__=Mock(return_value=False);r.status_code=code;r.headers={'Content-Type':'application/json'};r.iter_content.return_value=[json.dumps(data or {}).encode()];return r

def client():
    config=SimpleNamespace(api_base_url=SANDBOX,environment='Sandbox',client_id='org_test',api_version='20260507',get_password=lambda f:'secret')
    session=Mock();c=Client(config,Cache(),session);c.cache.set_value(c.token_key,'cached-token');return c,session

class ClientTests(unittest.TestCase):
    def test_write_timeout_is_unknown_and_never_replayed(self):
        c,s=client();s.request.side_effect=requests.Timeout('secret')
        with self.assertRaises(APIError) as exc:c.request('POST','/api/sales-invoices/MBP-1',{})
        self.assertTrue(exc.exception.uncertain);self.assertEqual(s.request.call_count,1);self.assertNotIn('secret',str(exc.exception))
    def test_write_500_is_unknown(self):
        c,s=client();s.request.return_value=response(500)
        with self.assertRaises(APIError) as exc:c.request('POST','/api/sales-invoices/MBP-1',{})
        self.assertTrue(exc.exception.uncertain)
    def test_400_is_definite(self):
        c,s=client();s.request.return_value=response(400,{'errors':{'field':'required'}})
        with self.assertRaises(APIError) as exc:c.request('POST','/api/sales-invoices/MBP-1',{})
        self.assertFalse(exc.exception.uncertain);self.assertEqual(exc.exception.detail,{'field':'required'})
    def test_invalid_write_json_is_unknown(self):
        c,s=client();r=response();r.iter_content.return_value=[b'<html>'];s.request.return_value=r
        with self.assertRaises(APIError) as exc:c.request('POST','/api/sales-invoices/MBP-1',{})
        self.assertTrue(exc.exception.uncertain)
    def test_redirects_not_followed(self):
        c,s=client();s.request.return_value=response(302)
        with self.assertRaises(APIError):c.request('GET','/api/sales-invoices/a')
        self.assertFalse(s.request.call_args.kwargs['allow_redirects'])
    def test_token_refresh_and_cache(self):
        c,s=client();c.cache.delete_value(c.token_key);s.request.side_effect=[response(200,dict(token='jwt',expires_at='2099-01-01T00:00:00Z')),response(200,dict(id='one'))]
        self.assertEqual(c.request('GET','/api/sales-invoices/a')['id'],'one');self.assertEqual(c.token(),'jwt');self.assertEqual(s.request.call_count,2)
    def test_token_relative_expiry(self):
        c,s=client();c.cache.delete_value(c.token_key)
        s.request.return_value=response(200,dict(token='jwt',expires_in=3600))
        self.assertEqual(c.token(),'jwt');self.assertEqual(c.token(),'jwt')
        self.assertEqual(s.request.call_count,1)

    def test_401_refresh_once(self):
        c,s=client();s.request.side_effect=[response(401),response(200,dict(token='new',expires_at='2099-01-01T00:00:00Z')),response(200,dict(id='ok'))]
        self.assertEqual(c.request('POST','/api/sales-invoices/p',{})['id'],'ok');self.assertEqual(s.request.call_count,3)
    def test_reject_untrusted_origin(self):
        for url in ['http://api.ae.ardentaxit.tax','https://evil.test','https://api.ae.ardentaxit.tax.evil.test','https://user:pass@api.ae.ardentaxit.tax','https://api.ae.ardentaxit.tax/path']:
            with self.subTest(url=url),self.assertRaises(ValueError):validate_base_url(url,'Production')
    def test_local_account_throttle(self):
        c,s=client();s.request.return_value=response(200,{'ok':True})
        for _ in range(45):c.request('GET','/api/sales-invoices/a')
        with self.assertRaises(APIError) as exc:c.request('GET','/api/sales-invoices/a')
        self.assertEqual(exc.exception.status,429);self.assertEqual(s.request.call_count,45)

if __name__=='__main__':unittest.main()
