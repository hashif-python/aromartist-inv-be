from datetime import date
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from apps.accounts.models import Role,UserRoleAssignment,UserBranchAssignment
from apps.hrms.models import Employee,Designation
from apps.pos.models import Register,Shift,Sale
from apps.pos.permissions import CASHIER
from tests import test_workflows as fixtures
class MobilePOS(TestCase):
 balance=fixtures.Workflows.balance
 sale=fixtures.Workflows.sale
 post=fixtures.Workflows.post
 def setUp(self):
  fixtures.Workflows.setUp(self);self.br.warehouse=self.wh;self.br.save()
  self.reg=Register.objects.create(organization=self.org,branch=self.br,name='Till')
  self.cashier=get_user_model().objects.create_user(username='mobile_cashier',password='Strong-POS-582!',organization=self.org,role='staff',branch=self.br)
  designation=Designation.objects.create(organization=self.org,name='Cashier')
  Employee.objects.create(organization=self.org,name='Cashier',employeeCode='MOB01',designation=designation,branch=self.br,joiningDate=date(2024,1,1),phone='555',user=self.cashier)
  self.role=Role.objects.create(organization=self.org,name='POS Cashier',permissions=list(CASHIER),scope='branches')
  UserRoleAssignment.objects.create(user=self.cashier,role=self.role);UserBranchAssignment.objects.create(user=self.cashier,branch=self.br);self.api.force_authenticate(self.cashier)
 def mobile(self,section,payload=None,status=200):
  if payload is None:r=self.api.get(f'/api/v1/pos/mobile/{section}/',{'branchId':self.br.pk})
  else:r=self.api.post(f'/api/v1/pos/mobile/{section}/',{'branchId':self.br.pk,**payload},format='json')
  self.assertEqual(r.status_code,status,r.data);return r.data
 def open(self):return self.mobile('shifts',{'registerId':self.reg.pk,'opening':'100'},201)
 def checkout(self,key='mobile-test-key',qty=1,**kwargs):return self.mobile('checkout',{'cart':[{'id':self.v.pk,'qty':qty}],'paymentMethod':'Cash','checkoutKey':key,**kwargs},201)
 def test_mobile_login_refresh(self):
  self.api.force_authenticate(None);r=self.mobile('login',{'username':'mobile_cashier','password':'Strong-POS-582!'})
  self.assertIn('refresh',r);r=self.api.post('/api/v1/auth/token/refresh/',{'refresh':r['refresh']},format='json');self.assertEqual(r.status_code,200)
 def test_unlinked_cashier_denied(self):
  self.cashier.employees.update(user=None);self.api.force_authenticate(None);self.mobile('login',{'username':'mobile_cashier','password':'Strong-POS-582!'},403)
 def test_stock_redaction_scope(self):
  rows=self.mobile('products');self.assertEqual(rows[0]['available'],20);self.assertNotIn('costPrice',rows[0]);self.assertNotIn('formulaId',rows[0])
  self.assertEqual(self.api.get('/api/v1/pos/mobile/stock/',{'branchId':self.br2.pk}).status_code,403)
 def test_checkout_idempotent_register_stock(self):
  shift=self.open();r=self.checkout();inv=r['invoice'];self.assertRegex(inv['invoiceNumber'],r'^INV-');self.assertEqual(self.balance(self.v,self.br),19)
  repeated=self.mobile('checkout',{'cart':[{'id':self.v.pk,'qty':1}],'paymentMethod':'Cash','checkoutKey':'mobile-test-key'},200);self.assertEqual(inv['id'],repeated['invoice']['id']);self.assertEqual(Sale.objects.count(),1)
  summary=self.mobile('shifts')[0];self.assertEqual(summary['cashSales'],599);self.assertEqual(summary['expected'],699)
  self.mobile('shifts/'+shift['id'],{'action':'close','counted':699});self.assertIsNotNone(Shift.objects.get(pk=shift['id']).closed_at)
 def test_stock_failure_atomic(self):
  self.open();self.mobile('checkout',{'cart':[{'id':self.v.pk,'qty':30}],'paymentMethod':'Cash','checkoutKey':'failure-key'},400);self.assertEqual(Sale.objects.count(),0);self.assertEqual(self.balance(self.v,self.br),20)
 def test_discount_paid_edit_denied(self):
  self.open();self.mobile('checkout',{'cart':[{'id':self.v.pk,'qty':1}],'paymentMethod':'Cash','checkoutKey':'discount-key','discount':1},403)
  inv=self.checkout()['invoice'];self.assertEqual(self.api.patch(f'/api/v1/pos/mobile/receipt/{inv["id"]}/',{'branchId':self.br.pk,'total':1},format='json').status_code,400)
 def test_draft_revision_finalization(self):
  d=self.mobile('drafts',{'payload':{'cart':[{'id':self.v.pk,'qty':1}]}},201);self.assertEqual(self.balance(self.v,self.br),20)
  self.mobile('drafts/'+d['id'],{'revision':0,'payload':d['payload']},400);self.open();self.checkout(draftId=d['id'],revision=d['revision']);self.mobile('drafts/'+d['id'],{'revision':2,'payload':d['payload']},400)
 def test_duplicate_register_cash_permission(self):
  shift=self.open();self.mobile('shifts',{'registerId':self.reg.pk,'opening':0},400);self.mobile('shifts/'+shift['id'],{'action':'cash','amount':1,'kind':'In','reason':'Float'},403)
 def test_return_permissions_stock_condition(self):
  self.open();inv=self.checkout()['invoice'];data={'invoiceNumber':inv['invoiceNumber'],'sku':self.v.sku,'qty':1,'reason':'Damaged','condition':'Damaged','returnKey':'refund-test-key'}
  self.mobile('returns',data,403);self.role.permissions+=['sales.return.create','pos.refund.process'];self.role.save();self.mobile('returns',data,201);self.assertEqual(self.balance(self.v,self.br),19);self.assertEqual(self.mobile('shifts')[0]['cashRefunds'],599)
 def test_other_cashier_hidden(self):
  self.api.force_authenticate(self.user);foreign=self.sale();self.api.force_authenticate(self.cashier);self.assertEqual(self.api.get(f'/api/v1/pos/mobile/receipt/{foreign["id"]}/',{'branchId':self.br.pk}).status_code,403)

 def test_refund_request_idempotent(self):
  self.role.permissions+=['sales.return.create','pos.refund.process'];self.role.save();self.open();inv=self.checkout()['invoice']
  data={'invoiceNumber':inv['invoiceNumber'],'sku':self.v.sku,'qty':1,'reason':'Damaged','condition':'Damaged','returnKey':'refund-retry-key'}
  first=self.mobile('returns',data,201);repeat=self.mobile('returns',data,200);self.assertEqual(first['id'],repeat['id']);self.assertEqual(self.mobile('shifts')[0]['cashRefunds'],599)
 def test_discrepancy_supervisor_approval(self):
  shift=self.open();result=self.mobile('shifts/'+shift['id'],{'action':'close','counted':0});self.assertTrue(result['closingRequested']);self.assertIsNone(result['closedAt'])
  self.api.force_authenticate(self.user);result=self.mobile('shifts/'+shift['id'],{'action':'close'});self.assertIsNotNone(result['closedAt']);self.assertEqual(result['closedBy'],self.user.pk)
 def test_pending_register_blocks_shared_web_checkout(self):
  from apps.erp import services
  shift=self.open();self.mobile('shifts/'+shift['id'],{'action':'close','counted':0})
  from rest_framework.exceptions import ValidationError
  with self.assertRaises(ValidationError):services.checkout(self.cashier,{'branchId':self.br.pk,'cart':[{'id':self.v.pk,'qty':1}]})
  self.assertEqual(self.balance(self.v,self.br),20)
 def test_missing_warehouse_and_short_cash(self):
  self.open();self.mobile('checkout',{'cart':[{'id':self.v.pk,'qty':1}],'paymentMethod':'Cash','checkoutKey':'short-cash-key','tendered':1},400);self.assertEqual(self.balance(self.v,self.br),20)
  self.br.warehouse=None;self.br.save();self.mobile('checkout',{'cart':[{'id':self.v.pk,'qty':1}],'paymentMethod':'Cash','checkoutKey':'warehouse-key'},400)

from concurrent.futures import ThreadPoolExecutor
from unittest import skipUnless
from django.db import connection,close_old_connections
from django.test import TransactionTestCase
from apps.erp import models as erp
@skipUnless(connection.vendor=='postgresql','PostgreSQL row locks require PostgreSQL')
class MobileConcurrency(TransactionTestCase):
 def setUp(self):
  fixtures.Workflows.setUp(self);self.br.warehouse=self.wh;self.br.save()
  register=Register.objects.create(organization=self.org,branch=self.br,name='Till');Shift.objects.create(organization=self.org,register=register,cashier=self.user,opening=0)
  self.second=get_user_model().objects.create_user(username='second_operator',organization=self.org,role='owner')
  second_register=Register.objects.create(organization=self.org,branch=self.br,name='Till 2');Shift.objects.create(organization=self.org,register=second_register,cashier=self.second,opening=0)
  erp.Stock.objects.filter(location=self.br,variant=self.v).update(quantity=1)
 def request(self,request):
  key,user_id=request if isinstance(request,tuple) else (request,self.user.pk)
  close_old_connections()
  try:
   api=APIClient();api.force_authenticate(get_user_model().objects.get(pk=user_id));return api.post('/api/v1/pos/mobile/checkout/',{'branchId':self.br.pk,'cart':[{'id':self.v.pk,'qty':1}],'paymentMethod':'Cash','checkoutKey':key},format='json').status_code
  finally:close_old_connections()
 def test_last_unit_simultaneous_cashiers(self):
  with ThreadPoolExecutor(max_workers=2) as pool:codes=list(pool.map(self.request,[('race-key-1',self.user.pk),('race-key-2',self.second.pk)]))
  self.assertEqual(sorted(codes),[201,400]);self.assertEqual(erp.Stock.objects.get(location=self.br,variant=self.v).quantity,0);self.assertEqual(erp.Invoice.objects.count(),1)
 def test_same_key_simultaneous_pay(self):
  with ThreadPoolExecutor(max_workers=4) as pool:codes=list(pool.map(self.request,['one-sale-key']*4))
  self.assertEqual(sorted(codes),[200,200,200,201]);self.assertEqual(erp.Invoice.objects.count(),1)
