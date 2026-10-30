"""Run only on an isolated ERPNext 15/16 site. All provider HTTP is mocked."""
import json
import unittest
import uuid
from unittest.mock import patch, Mock

import frappe
from frappe.utils import nowdate, add_days
from addons_einvoicing import api, jobs
from addons_einvoicing.client import APIError
from addons_einvoicing.domain import canonical, signature
from addons_einvoicing.service import internal_save
from addons_einvoicing.webhooks import accept, process

class TestArdentaxIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        frappe.set_user('Administrator')
        cls.company='Addons EInvoice Test Company'
        cls.customer='Addons EInvoice Test Buyer'
        cls.item='ADDONS-EINV-TEST-SERVICE'
        from erpnext.setup.setup_wizard.operations.install_fixtures import install
        if not frappe.db.exists('Warehouse Type','Transit'):install('United Arab Emirates')
        if not frappe.db.exists('Company',cls.company):
            frappe.get_doc(dict(doctype='Company',company_name=cls.company,abbr='AXE',default_currency='AED',country='United Arab Emirates',chart_of_accounts='Standard')).insert()
        if not frappe.db.exists('Customer',cls.customer):
            frappe.get_doc(dict(doctype='Customer',customer_name=cls.customer,customer_type='Company',customer_group=frappe.db.get_value('Customer Group',{'is_group':0},'name'),territory='All Territories',custom_addons_einv_legal_name='Addons EInvoice Test Buyer LLC',custom_addons_einv_email='buyer@example.test',custom_addons_einv_tin='1000000001',custom_addons_einv_endpoint_id='1000000001',custom_addons_einv_endpoint_scheme='0235')).insert()
        cls.address=frappe.db.get_value('Address',{'address_title':'Addons EInvoice Test Address'},'name')
        if not cls.address:
            cls.address=frappe.get_doc(dict(doctype='Address',address_title='Addons EInvoice Test Address',address_type='Billing',address_line1='Test Street',city='Dubai',country='United Arab Emirates',custom_addons_einv_region='DXB',links=[dict(link_doctype='Customer',link_name=cls.customer)])).insert().name
        if not frappe.db.exists('Item',cls.item):
            frappe.get_doc(dict(doctype='Item',item_code=cls.item,item_name='Test service',item_group=frappe.db.get_value('Item Group',{'is_group':0},'name'),stock_uom='Nos',is_stock_item=0)).insert()
        if not frappe.db.exists('Price List','Addons EInvoice Test Selling'):
            frappe.get_doc(dict(doctype='Price List',price_list_name='Addons EInvoice Test Selling',selling=1,currency='AED',enabled=1)).insert()
        fiscal='Addons EInvoice Test '+nowdate()[:4]
        if not frappe.db.exists('Fiscal Year',fiscal):
            frappe.get_doc(dict(doctype='Fiscal Year',year=fiscal,year_start_date=nowdate()[:4]+'-01-01',year_end_date=nowdate()[:4]+'-12-31',companies=[dict(company=cls.company)])).insert()
        cls.tax=frappe.db.get_value('Account',{'company':cls.company,'account_type':'Tax','is_group':0},'name')
        if not cls.tax:
            parent=frappe.db.get_value('Account',{'company':cls.company,'root_type':'Liability','is_group':1},'name')
            cls.tax=frappe.get_doc(dict(doctype='Account',company=cls.company,account_name='Ardentax VAT',parent_account=parent,account_type='Tax')).insert().name
        frappe.db.commit()

    def setUp(self):
        frappe.set_user('Administrator')
        frappe.db.savepoint('ardentax_test')
        self.enqueue=patch('frappe.enqueue').start()
        self.no_network=patch('requests.sessions.Session.request',side_effect=AssertionError('Live network forbidden in tests')).start()
        self.commit=patch.object(frappe.db,'commit').start()
        self.config=frappe.get_doc(dict(doctype='Addons E Invoice Settings',company=self.company,enabled=1,auto_submit=1,environment='Sandbox',api_base_url='https://api-sandbox.ae.ardentaxit.tax',api_version='20260507',org_id='00000000-0000-4000-8000-000000000001',business_profile_id='MBP-TEST',client_id='org_test',client_secret='not-a-real-secret',webhook_secret='test-webhook-secret',credit_notes_verified=1,uom_mappings=[dict(uom='Nos',unit_code='EA')],tax_mappings=[dict(category='S',rate=5)])).insert()

    def tearDown(self):
        frappe.set_user('Administrator')
        patch.stopall()
        frappe.db.rollback(save_point='ardentax_test')
        frappe.clear_cache()

    def invoice(self,submit=True):
        invoice=frappe.get_doc(dict(doctype='Sales Invoice',company=self.company,customer=self.customer,customer_address=self.address,posting_date=nowdate(),due_date=add_days(nowdate(),30),currency='AED',selling_price_list='Addons EInvoice Test Selling',custom_addons_einv_enabled=1,custom_addons_einv_payment_code='30',disable_rounded_total=1,items=[dict(item_code=self.item,qty=2,rate=100)],taxes=[dict(charge_type='On Net Total',account_head=self.tax,description='VAT',rate=5)])).insert()
        if submit:invoice.submit()
        return invoice

    def submission(self,invoice):
        return frappe.get_doc('Addons E Invoice Submission',frappe.db.get_value('Addons E Invoice Submission',{'sales_invoice':invoice.name},'name'))

    def response(self,doc,status='APPROVED'):
        return dict(id='00000000-0000-4000-8000-000000000002',org_id=self.config.org_id,document_number=doc.sales_invoice,document_currency_code='AED',accounting_supplier_party={'profile_id':self.config.business_profile_id},is_phase2_document=True,meta_info={'peppol_status':{'overall_status':status,'participant_status':'APPROVED' if status=='APPROVED' else None,'fta_status':'APPROVED' if status=='APPROVED' else None}},**json.loads(doc.expected_json))

    def event(self,resource=None):
        return dict(org_id=self.config.org_id,profile_id=self.config.business_profile_id,resource_id=resource or '00000000-0000-4000-8000-000000000002',event_type='sale.invoice.update',webhook_event_id=str(uuid.uuid4()),event_timestamp='2026-10-16T10:00:00Z',resource_url='https://evil.example/should-never-be-followed')

    def test_install_and_custom_fields(self):
        from addons_einvoicing.install import setup
        setup();setup()
        self.assertTrue(frappe.get_meta('Sales Invoice').has_field('custom_addons_einv_enabled'))
        self.assertTrue(frappe.db.exists('Workspace','Addons - E invoicing'))

    def test_invoice_hook_and_duplicate_queue(self):
        inv=self.invoice();doc=self.submission(inv)
        self.assertEqual(doc.status,'Queued');self.assertEqual(json.loads(doc.expected_json)['payable_amount'],210)
        self.assertEqual(api.queue_invoice(inv.name),doc.name)
        self.assertEqual(frappe.db.count('Addons E Invoice Submission',{'sales_invoice':inv.name}),1)
        self.assertTrue(any(c.kwargs.get('enqueue_after_commit') for c in self.enqueue.call_args_list))

    def test_preview_draft_no_submission(self):
        inv=self.invoice(False);result=api.preview(inv.name)
        self.assertEqual(result['expected']['tax_amount'],10)
        self.assertFalse(frappe.db.exists('Addons E Invoice Submission',{'sales_invoice':inv.name}))

    def test_worker_approved_and_not_replayed(self):
        inv=self.invoice();doc=self.submission(inv);remote=Mock();remote.request.return_value=self.response(doc)
        with patch('addons_einvoicing.jobs.client',return_value=remote):
            jobs.send(doc.name);jobs.send(doc.name)
        doc.reload();self.assertEqual(doc.status,'Approved');self.assertEqual(remote.request.call_count,1)
        self.assertTrue(self.commit.called)
        self.assertTrue(frappe.db.count('Addons E Invoice Audit',{'submission':doc.name})>=2)
        with self.assertRaises(frappe.ValidationError):inv.cancel()

    def test_timeout_recovers_without_second_post(self):
        inv=self.invoice();doc=self.submission(inv);remote=Mock();remote.request.side_effect=APIError('Timeout',uncertain=True)
        with patch('addons_einvoicing.jobs.client',return_value=remote):jobs.send(doc.name);jobs.send(doc.name)
        doc.reload();self.assertEqual(doc.status,'Unknown');self.assertEqual(remote.request.call_count,1)
        with self.assertRaises(frappe.ValidationError):api.correct_and_retry(doc.name)
        remote.request.side_effect=[{'content':[self.response(doc)],'total_pages':1},self.response(doc)]
        with patch('addons_einvoicing.jobs.client',return_value=remote):jobs.refresh(doc.name)
        self.assertEqual(doc.reload().status,'Approved')
        self.assertEqual([x.args[0] for x in remote.request.call_args_list],['POST','GET','GET'])

    def test_unknown_absence_does_not_recreate(self):
        doc=self.submission(self.invoice());doc.status='Unknown';internal_save(doc)
        remote=Mock();remote.request.return_value={'content':[],'total_pages':0}
        with patch('addons_einvoicing.jobs.client',return_value=remote):jobs.refresh(doc.name)
        self.assertEqual(doc.reload().status,'Unknown');self.assertEqual(remote.request.call_args.args[0],'GET')

    def test_amount_mismatch_retains_uuid(self):
        doc=self.submission(self.invoice());response=self.response(doc);response['tax_amount']=99
        remote=Mock();remote.request.return_value=response
        with patch('addons_einvoicing.jobs.client',return_value=remote):jobs.send(doc.name)
        doc.reload();self.assertEqual(doc.status,'Mismatch');self.assertTrue(doc.provider_uuid)
        with self.assertRaises(frappe.ValidationError):api.correct_and_retry(doc.name)

    def test_definite_error_can_rebuild(self):
        doc=self.submission(self.invoice());remote=Mock();remote.request.side_effect=APIError('Bad request',400)
        with patch('addons_einvoicing.jobs.client',return_value=remote):jobs.send(doc.name)
        self.assertEqual(doc.reload().status,'Error');api.correct_and_retry(doc.name)
        self.assertEqual(doc.reload().status,'Queued')

    def test_validation_failed_put_requires_fresh_eligibility(self):
        doc=self.submission(self.invoice());jobs.apply_response(doc,self.response(doc,'VALIDATION_FAILED'))
        api.correct_and_retry(doc.name)
        remote=Mock();remote.request.side_effect=[self.response(doc,'VALIDATION_FAILED'),self.response(doc)]
        with patch('addons_einvoicing.jobs.client',return_value=remote):jobs.send(doc.name)
        self.assertEqual([x.args[0] for x in remote.request.call_args_list],['GET','PUT'])
        self.assertEqual(doc.reload().status,'Approved')

    def test_cancel_before_attempt_stops_queue(self):
        inv=self.invoice();doc=self.submission(inv);inv.cancel()
        self.assertEqual(doc.reload().status,'Stopped')

    def test_generic_record_mutation_and_flag_forgery_blocked(self):
        doc=self.submission(self.invoice());doc.status='Approved';doc.flags.addons_einv_internal=True
        with self.assertRaises(frappe.PermissionError):doc.save(ignore_permissions=True)

    def test_connection_identity_frozen(self):
        self.invoice();self.config.environment='Production';self.config.api_base_url='https://api.ae.ardentaxit.tax';self.config.production_verified=1
        with self.assertRaises(frappe.ValidationError):self.config.save()

    def test_webhook_signature_deduplication(self):
        body=canonical(self.event()).encode();sig=signature('test-webhook-secret',body)
        self.assertFalse(accept(self.config.name,body,sig)['duplicate']);self.assertTrue(accept(self.config.name,body,sig)['duplicate'])
        with self.assertRaises(frappe.AuthenticationError):accept(self.config.name,body,b'bad'.decode())
        self.assertEqual(frappe.db.count('Addons E Invoice Webhook Event',{'connection':self.config.name}),1)

    def test_cross_org_webhook_rejected(self):
        event=self.event();event['org_id']='other';body=canonical(event).encode()
        with self.assertRaises(frappe.ValidationError):accept(self.config.name,body,signature('test-webhook-secret',body))

    def test_webhook_ignores_resource_url_and_creates_inbox(self):
        event=self.event();body=canonical(event).encode();accept(self.config.name,body,signature('test-webhook-secret',body))
        name=frappe.db.get_value('Addons E Invoice Webhook Event',{'webhook_event_id':event['webhook_event_id']},'name')
        remote=Mock();remote.request.return_value={'id':event['resource_id'],'org_id':self.config.org_id,'accounting_supplier_party':{'profile_id':self.config.business_profile_id},'document_number':'EXTERNAL-1'}
        with patch('addons_einvoicing.webhooks.client',return_value=remote):process(name)
        self.assertEqual(remote.request.call_args.args[1],'/api/sales-invoices/'+event['resource_id'])
        self.assertEqual(frappe.db.get_value('Addons E Invoice Webhook Event',name,'status'),'Processed')
        self.assertTrue(frappe.db.exists('Addons E Invoice Inbox',{'provider_uuid':event['resource_id']}))

    def test_operator_role_required(self):
        inv=self.invoice(False);frappe.set_user('Guest')
        with self.assertRaises(frappe.PermissionError):api.preview(inv.name)

    def test_private_artifacts(self):
        doc=self.submission(self.invoice());jobs.apply_response(doc,self.response(doc))
        from io import BytesIO
        from pypdf import PdfWriter
        buffer=BytesIO();writer=PdfWriter();writer.add_blank_page(width=72,height=72);writer.write(buffer)
        remote=Mock();remote.request.side_effect=[(buffer.getvalue(), 'application/pdf'),(b'<?xml version="1.0"?><Invoice/>','application/xml')]
        with patch('addons_einvoicing.api.client',return_value=remote):api.download_artifacts(doc.name)
        doc.reload()
        for url in (doc.pdf_file,doc.xml_file):
            self.assertTrue(url.startswith('/private/files/'))
            self.assertEqual(frappe.db.get_value('File',{'file_url':url},'is_private'),1)

    def test_link_unknown_by_verified_uuid(self):
        doc=self.submission(self.invoice());doc.status='Unknown';internal_save(doc)
        remote=Mock();remote.request.return_value=self.response(doc)
        with patch('addons_einvoicing.api.client',return_value=remote):api.link_existing(doc.name,remote.request.return_value['id'])
        self.assertEqual(doc.reload().status,'Approved')
        self.assertEqual(remote.request.call_args.args[0],'GET')

    def test_wrong_profile_never_links(self):
        doc=self.submission(self.invoice());doc.status='Unknown';internal_save(doc)
        remote=Mock();response=self.response(doc);response['accounting_supplier_party']['profile_id']='MBP-OTHER';remote.request.return_value=response
        with patch('addons_einvoicing.api.client',return_value=remote),self.assertRaises(ValueError):api.link_existing(doc.name,response['id'])
        self.assertFalse(doc.reload().provider_uuid)

    def test_disabled_connection_blocks_send(self):
        doc=self.submission(self.invoice());self.config.enabled=0;self.config.save()
        with self.assertRaises(frappe.ValidationError):jobs.send(doc.name)
        self.no_network.assert_not_called();self.assertEqual(doc.reload().attempts,0)

    def test_non_admin_operator_can_read_and_queue(self):
        inv=self.invoice(False)
        email='ardentax-operator@example.test'
        if not frappe.db.exists('User',email):
            frappe.get_doc(dict(doctype='User',email=email,first_name='Addons E Invoice Operator',send_welcome_email=0,roles=[dict(role='Accounts User'),dict(role='Accounts Manager'),dict(role='Addons E Invoice Operator')])).insert()
        frappe.set_user(email)
        api.preview(inv.name)
        inv=frappe.get_doc('Sales Invoice',inv.name);inv.submit()
        name=api.queue_invoice(inv.name)
        doc=frappe.get_doc('Addons E Invoice Submission',name);doc.check_permission('read')
        self.assertEqual(doc.status,'Queued')
        with self.assertRaises(frappe.PermissionError):frappe.get_doc('Addons E Invoice Settings',self.config.name).check_permission('read')

    def test_credit_note_from_approved_original(self):
        original=self.invoice();doc=self.submission(original);jobs.apply_response(doc,self.response(doc))
        from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return
        credit=make_sales_return(original.name);credit.custom_addons_einv_discrepancy='DL8.61.1.A';credit.custom_addons_einv_enabled=1
        credit.insert();credit.submit()
        credit_doc=self.submission(credit);payload=json.loads(credit_doc.request_json)
        self.assertEqual(payload['document_lines'][0]['quantity'],2)
        self.assertEqual(payload['billing_reference'][0]['id'],original.name)

    def test_dashboard_and_bulk_queue(self):
        first=self.invoice();second=self.invoice()
        names=api.queue_invoices([first.name,second.name,first.name])
        self.assertEqual(len(names),2)
        data=api.dashboard()
        self.assertTrue(any(row['name']==names[0] for row in data['recent']))
        self.assertTrue(any(row['status']=='Queued' and row['total']>=2 for row in data['counts']))

    def test_bulk_validation_before_queue(self):
        first=self.invoice(False);second=self.invoice(False)
        self.config.auto_submit=0;self.config.save();first.submit()
        before=frappe.db.count('Addons E Invoice Submission')
        with self.assertRaises(frappe.ValidationError):api.queue_invoices([first.name,second.name])
        self.assertEqual(frappe.db.count('Addons E Invoice Submission'),before)
        for value in ([], 'not a list', [first.name]*51, [42]):
            with self.assertRaises((frappe.ValidationError,ValueError)):api.queue_invoices(value)

    def test_dashboard_rejects_guest(self):
        frappe.set_user('Guest')
        with self.assertRaises(frappe.PermissionError):api.dashboard()

    def fynamics_config(self):
        frappe.db.set_value('Company',self.company,'tax_id','100000000000003')
        frappe.db.set_value('Customer',self.customer,'tax_id','100000000000003')
        address=frappe.get_doc(dict(doctype='Address',address_title='Fynamics Supplier Test',address_type='Billing',address_line1='Supplier Street',city='Dubai',country='United Arab Emirates',custom_addons_einv_region='DXB',links=[dict(link_doctype='Company',link_name=self.company)])).insert()
        self.config.update(dict(provider='Fynamics',api_base_url='https://sandbox-uae.fynamicstax.com',supplier_address=address.name,supplier_endpoint='1000000000',supplier_scheme='0235',supplier_registration='TL-TEST',supplier_registration_scheme='TL',supplier_authority='Test Authority',supplier_email='supplier@example.test'))
        self.config.save()
        return self.config

    def fynamics_status(self,doc,status='SUCCESS'):
        return dict(messageUuid=doc.provider_uuid,documentType='Invoice',documentStatus=status,to_c3={'mls':{'responseCode':'AP'}},to_c5={'mls':{'responseCode':'AP'}})

    def test_fynamics_submit_poll_credit(self):
        from addons_einvoicing import fynamics_service as fy
        self.fynamics_config();invoice=self.invoice();doc=self.submission(invoice)
        self.assertEqual(doc.provider,'Fynamics');self.assertIn('AccountingSupplierParty',json.loads(doc.request_json))
        c=Mock();c.request.return_value={'uuid':'123e4567-e89b-12d3-a456-426614174000'}
        with patch.object(fy,'client',return_value=c):jobs.send(doc.name)
        doc.reload();self.assertEqual(doc.status,'Processing');self.assertEqual(doc.overall_status,'QUEUED')
        c.request.return_value=self.fynamics_status(doc)
        with patch.object(fy,'client',return_value=c):jobs.refresh(doc.name)
        doc.reload();self.assertEqual(doc.status,'Approved');self.assertIn('does not return invoice amounts',doc.reconciliation_note)
        from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return
        credit=make_sales_return(invoice.name);credit.custom_addons_einv_discrepancy='VD';credit.custom_addons_einv_enabled=1;credit.insert();credit.submit()
        payload=json.loads(self.submission(credit).request_json)
        self.assertEqual(payload['Invoice']['InvoiceTypeCode'],'381')
        self.assertEqual(payload['BillingReference'][0]['ID'],invoice.name)
        with self.assertRaises(frappe.ValidationError):self.config.provider='ArdentaxIT';self.config.api_base_url='https://api-sandbox.ae.ardentaxit.tax';self.config.save()

    def test_fynamics_timeout_not_reposted_or_linked(self):
        from addons_einvoicing import fynamics_service as fy
        self.fynamics_config();doc=self.submission(self.invoice());c=Mock();c.request.side_effect=APIError('timeout',uncertain=True)
        with patch.object(fy,'client',return_value=c):
            jobs.send(doc.name);jobs.send(doc.name);jobs.refresh(doc.name)
        self.assertEqual(doc.reload().status,'Unknown');self.assertEqual(c.request.call_count,1)
        with self.assertRaises(frappe.ValidationError):api.link_existing(doc.name,'123e4567-e89b-12d3-a456-426614174000')

    def test_fynamics_webhook_dedupe_and_repoll(self):
        import hmac,hashlib
        from addons_einvoicing import fynamics_service as fy
        self.fynamics_config();doc=self.submission(self.invoice());doc.provider_uuid='123e4567-e89b-12d3-a456-426614174000';doc.status='Processing';internal_save(doc)
        body=canonical(self.fynamics_status(doc)).encode()
        sig='sha256='+hmac.new(b'test-webhook-secret',body,hashlib.sha256).hexdigest()
        self.assertFalse(fy.accept(self.config,body,sig)['duplicate']);self.assertTrue(fy.accept(self.config,body,sig)['duplicate'])
        with self.assertRaises(frappe.AuthenticationError):fy.accept(self.config,body+b' ',sig)
        event=frappe.get_doc('Addons E Invoice Webhook Event',frappe.db.get_value('Addons E Invoice Webhook Event',{'connection':self.config.name},'name'))
        c=Mock();c.request.return_value=self.fynamics_status(doc,'QUEUED')
        with patch.object(fy,'client',return_value=c):process(event.name)
        self.assertEqual(event.reload().status,'Processed');self.assertEqual(doc.reload().status,'Processing')
        changed=json.loads(body);changed['documentStatus']='FAILED';raw=canonical(changed).encode();sig='sha256='+hmac.new(b'test-webhook-secret',raw,hashlib.sha256).hexdigest()
        self.assertFalse(fy.accept(self.config,raw,sig)['duplicate'])

    def test_fynamics_webhook_poll_failure_retries(self):
        import hmac,hashlib
        from addons_einvoicing import fynamics_service as fy
        self.fynamics_config();doc=self.submission(self.invoice());doc.provider_uuid='123e4567-e89b-12d3-a456-426614174000';doc.status='Processing';internal_save(doc)
        body=canonical(self.fynamics_status(doc)).encode();sig='sha256='+hmac.new(b'test-webhook-secret',body,hashlib.sha256).hexdigest();fy.accept(self.config,body,sig)
        event=frappe.get_doc('Addons E Invoice Webhook Event',frappe.db.get_value('Addons E Invoice Webhook Event',{'connection':self.config.name},'name'))
        c=Mock();c.request.side_effect=APIError('unavailable',503)
        with patch.object(fy,'client',return_value=c):process(event.name)
        self.assertEqual(event.reload().status,'Error');self.assertEqual(event.attempts,1)

    def test_fynamics_artifacts_and_trn_guard(self):
        from addons_einvoicing import fynamics_service as fy
        from io import BytesIO
        from pypdf import PdfWriter
        self.fynamics_config();doc=self.submission(self.invoice());doc.provider_uuid='123e4567-e89b-12d3-a456-426614174000';doc.status='Processing';internal_save(doc)
        status=self.fynamics_status(doc);status['print_url']='https://sandbox-uae.fynamicstax.com/api/partner/sales-invoice/print-from-url/abc'
        pdf=BytesIO();w=PdfWriter();w.add_blank_page(width=100,height=100);w.write(pdf)
        c=Mock();c.base=self.config.api_base_url;c.request.side_effect=[status,(pdf.getvalue(),'application/pdf')]
        with patch.object(fy,'client',return_value=c):result=api.download_artifacts(doc.name)
        self.assertTrue(result['pdf_file'].startswith('/private/files/'))
        frappe.db.set_value('Company',self.company,'tax_id','100000000001003')
        with self.assertRaises(ValueError):jobs.refresh(doc.name)
