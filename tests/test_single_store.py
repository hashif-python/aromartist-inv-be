from io import StringIO
from django.test import TestCase
from django.core.management import call_command,CommandError
from django.contrib.auth import get_user_model
from django.db import connection
from rest_framework.test import APIClient
from apps.accounts.models import Organization
from apps.erp import models as m
from tests import test_workflows as fixtures

class StoreResetTests(TestCase):
 post=fixtures.Workflows.post
 setUp=fixtures.Workflows.setUp
 def reset(self,**extra):
  self.user.is_superuser=True;self.user.is_staff=True;self.user.save()
  call_command('reset_single_store',username=self.user.username,confirm_reset='RESET-ALL-DATA',stdout=StringIO(),**extra)
  self.user.refresh_from_db();self.org.refresh_from_db()
 def test_reset_preserves_admin_password_and_removes_operations(self):
  password=self.user.password
  get_user_model().objects.create_user(username='deleted-staff',password='Other-password-102!',organization=self.org)
  fixtures.Workflows.sale(self)
  from apps.hrms.models import Designation,Employee
  designation=Designation.objects.create(organization=self.org,name='Cashier',code='CASH')
  Employee.objects.create(organization=self.org,name='Employee',employeeCode='EMP',phone='999',joiningDate='2026-01-01',designation=designation,branch=self.br)
  self.reset();connection.check_constraints()
  self.assertEqual(self.user.password,password);self.assertTrue(self.user.check_password('Strong-test-238!'));self.assertEqual(get_user_model().objects.count(),1)
  self.assertEqual(Organization.objects.count(),1);self.assertTrue(self.org.singleLocationMode)
  self.assertEqual(m.Location.objects.filter(kind='Branch').count(),1);self.assertEqual(m.Location.objects.filter(kind='Warehouse').count(),1)
  self.assertEqual(self.org.defaultWarehouse.ownerBranch_id,self.org.defaultBranch_id);self.assertEqual(self.org.defaultBranch.warehouse_id,self.org.defaultWarehouse_id)
  for model in [m.Product,m.Variant,m.Fragrance,m.Formula,m.MaterialCategory,m.Material,m.Stock,m.Movement,m.Invoice,m.InvoiceLine,m.Supplier,m.Customer,Employee]:self.assertEqual(model.objects.count(),0,model.__name__)
  self.api.force_authenticate(None);r=self.api.post('/api/v1/auth/login/',dict(username=self.user.username,password='Strong-test-238!'),format='json');self.assertEqual(r.status_code,200,r.data);self.assertTrue(r.data['user']['storeSetup']['singleLocationMode'])
 def test_wrong_confirmation_and_non_admin_abort(self):
  before=m.Material.objects.count()
  with self.assertRaises(CommandError):call_command('reset_single_store',username=self.user.username,confirm_reset='NO',stdout=StringIO())
  with self.assertRaises(CommandError):call_command('reset_single_store',username=self.user.username,confirm_reset='RESET-ALL-DATA',stdout=StringIO())
  self.assertEqual(m.Material.objects.count(),before)
 def test_repeat_reset_leaves_one_location_pair(self):
  self.reset();self.reset();self.assertEqual(m.Location.objects.count(),2);self.assertEqual(get_user_model().objects.count(),1);connection.check_constraints()
 def test_default_location_services_and_new_locations_blocked(self):
  self.reset()
  from apps.erp import services as s
  self.assertEqual(s.location(self.user,None,'Branch').pk,self.org.defaultBranch_id);self.assertEqual(s.location(self.user,None,'Warehouse').pk,self.org.defaultWarehouse_id)
  r=self.api.post('/api/v1/warehouses/',dict(name='Extra',code='EXTRA'),format='json');self.assertEqual(r.status_code,400,r.data)
  r=self.api.delete('/api/v1/branches/'+self.org.defaultBranch_id+'/');self.assertEqual(r.status_code,400,r.data)
  r=self.api.post('/api/v1/transfers/',{},format='json');self.assertEqual(r.status_code,400,r.data)
 def test_purchase_and_adjustment_use_default_warehouse_without_selector(self):
  self.reset()
  supplier=m.Supplier.objects.create(organization=self.org,name='Supplier',code='SUP')
  cat=m.MaterialCategory.objects.create(organization=self.org,name='Oil',categoryType='Perfume Oil',unit='ml')
  material=m.Material.objects.create(organization=self.org,name='Oil stock',code='OIL',categoryRef=cat,category=cat.name,unit='ml')
  r=self.api.post('/api/v1/purchases/orders/',dict(supplierName=supplier.name,orderDate='2026-10-12',expectedDate='2026-10-12',items=[dict(material=material.name,qty=100,rate=1)]),format='json');self.assertEqual(r.status_code,201,r.data)
  self.assertEqual(m.PurchaseOrder.objects.get().warehouse_id,self.org.defaultWarehouse_id)
  r=self.api.post('/api/v1/inventory/adjustments/',dict(itemId=material.pk,itemType='Raw Material',quantity=100,adjustmentType='add',reason='Opening'),format='json');self.assertEqual(r.status_code,201,r.data)
  self.assertEqual(m.Stock.objects.get(material=material).location_id,self.org.defaultWarehouse_id)

class FragranceWithoutFamilyTests(TestCase):
 setUp=fixtures.Workflows.setUp
 def test_creation_requires_no_family(self):
  r=self.api.post('/api/v1/fragrances/',dict(name='Rose scent',perfumeOilId=self.oil.pk),format='json')
  self.assertEqual(r.status_code,201,r.data)
  self.assertNotIn('olfactoryFamily',r.data)
 def test_family_endpoint_removed(self):
  self.assertEqual(self.api.get('/api/v1/olfactory-families/').status_code,404)

class SingleWarehouseSaleTests(TestCase):
 def setUp(self):
  from tests import test_direct_perfume
  test_direct_perfume.DirectPerfumeTests.setUp(self)
  warehouse=m.Location.objects.create(organization=self.org,name='Only warehouse',code='WH01',kind='Warehouse',ownerBranch=self.br)
  self.org.singleLocationMode=True;self.org.defaultBranch=self.br;self.org.defaultWarehouse=warehouse;self.org.save()
  self.br.warehouse=warehouse;self.br.save();self.user.warehouse=warehouse;self.user.save()
  m.Stock.objects.filter(location=self.br).update(location=warehouse)
 def test_pos_without_branch_deducts_only_default_warehouse(self):
  from tests import test_direct_perfume
  p=test_direct_perfume.DirectPerfumeTests.product(self)
  body=dict(paymentMethod='Cash',checkoutKey='single-warehouse-sale',cart=[dict(productId=p['id'],recipeRevision=p['recipeRevision'],pricingToken=p['pricingToken'],qty=2)])
  r=self.api.post('/api/v1/perfume-quote/',body,format='json');self.assertEqual(r.status_code,200,r.data)
  r=self.api.post('/api/v1/sales/pos/checkout/',body,format='json');self.assertEqual(r.status_code,201,r.data)
  self.assertEqual(m.Invoice.objects.get().branch_id,self.br.pk)
  self.assertEqual(m.Stock.objects.get(location=self.org.defaultWarehouse,material=self.ingredients[0]).quantity,960)
  self.assertEqual(m.Stock.objects.get(location=self.other,material=self.ingredients[0]).quantity,1000)
  self.assertEqual(m.Stock.objects.filter(location=self.br).count(),0)
  for material in self.packaging:self.assertEqual(m.Stock.objects.get(location=self.org.defaultWarehouse,material=material).quantity,98)
 def test_non_default_branch_rejected(self):
  from tests import test_direct_perfume
  p=test_direct_perfume.DirectPerfumeTests.product(self)
  r=test_direct_perfume.DirectPerfumeTests.checkout(self,p,branchId=self.other.pk);self.assertEqual(r.status_code,400,r.data)

class SingleAccountDefaultsTests(TestCase):
 setUp=fixtures.Workflows.setUp
 post=fixtures.Workflows.post
 reset=StoreResetTests.reset
 def test_new_cashier_gets_default_branch_without_selection(self):
  from apps.accounts.models import Role
  self.reset();role=Role.objects.get(organization=self.org,name='Cashier')
  r=self.api.post('/api/v1/access/users/',dict(username='new-cashier',password='Strong-new-cashier-293!',roles=[role.pk],is_active=True),format='json')
  self.assertEqual(r.status_code,201,r.data)
  user=get_user_model().objects.get(username='new-cashier');self.assertEqual(user.branch_id,self.org.defaultBranch_id);self.assertEqual(user.warehouse_id,self.org.defaultWarehouse_id)
