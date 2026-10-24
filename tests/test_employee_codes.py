from datetime import date
from decimal import Decimal
from tempfile import TemporaryDirectory
from io import StringIO
from concurrent.futures import ThreadPoolExecutor
from unittest import skipUnless
from django.db import connection,transaction,close_old_connections
from django.test import TestCase,TransactionTestCase
from django.core.management import call_command
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from apps.accounts.models import Organization,Role,UserRoleAssignment,UserBranchAssignment
from apps.erp import models as e
from apps.hrms import models as h
from apps.common.services.code_generator import allocate

class EmployeeCodes(TestCase):
 def setUp(self):
  self.org=Organization.objects.create(name='Numbering');self.owner=get_user_model().objects.create_user(username='codes_owner',organization=self.org,role='owner');self.api=APIClient();self.api.force_authenticate(self.owner)
  self.branch=e.Location.objects.create(organization=self.org,name='Branch',kind='Branch');self.designation=h.Designation.objects.create(organization=self.org,name='Executive')
 def employee(self,name='Person'):
  response=self.api.post('/api/v1/hrms/employees/',dict(name=name,phone='555',email='person@example.com',joiningDate='2024-01-01',designation=self.designation.pk,branch=self.branch.pk),format='json');self.assertEqual(response.status_code,201,response.data);return response.data
 def test_employee_create_edit_no_department_code_readonly(self):
  data=self.employee();self.assertRegex(data['employeeCode'],r'^EMP-\d{6}$');self.assertIsNone(h.Employee.objects.get(pk=data['id']).department)
  response=self.api.patch(f'/api/v1/hrms/employees/{data["id"]}/',{'name':'Edited','employeeCode':'OVERRIDE'},format='json');self.assertEqual(response.status_code,200,response.data);self.assertEqual(response.data['employeeCode'],data['employeeCode'])
  legacy=h.Department.objects.create(organization=self.org,name='Historical');h.Employee.objects.filter(pk=data['id']).update(department=legacy)
  self.api.patch(f'/api/v1/hrms/employees/{data["id"]}/',{'name':'Keep history'},format='json');self.assertEqual(h.Employee.objects.get(pk=data['id']).department_id,legacy.pk)
 def test_supplier_master_codes_and_no_recycling(self):
  r=self.api.post('/api/v1/suppliers/',{'name':'Vendor'},format='json');self.assertEqual(r.status_code,201,r.data);first=r.data['code'];self.assertRegex(first,r'^SUP-\d{6}$')
  self.api.delete(f'/api/v1/suppliers/{r.data["id"]}/');r=self.api.post('/api/v1/suppliers/',{'name':'Next vendor'},format='json');self.assertNotEqual(r.data['code'],first)
  old=e.Supplier.objects.create(organization=self.org,name='Imported vendor',code='LEGACY-VENDOR');old.name='Updated vendor';old.save();self.assertEqual(old.code,'LEGACY-VENDOR')
 def test_collision_skip_persistence_configuration_and_rollback(self):
  e.Supplier.objects.create(organization=self.org,name='Reserved legacy',code='SUP-000001')
  supplier=e.Supplier.objects.create(organization=self.org,name='Generated');self.assertEqual(supplier.code,'SUP-000002')
  sequence=e.CodeSequence.objects.get(documentType='erp.supplier.SUP');sequence.refresh_from_db();self.assertEqual(sequence.nextSequence,3)
  try:
   with transaction.atomic():
    e.Supplier.objects.create(organization=self.org,name='Failed record')
    raise ValueError('Rollback')
  except ValueError:pass
  self.assertFalse(e.Supplier.objects.filter(name='Failed record').exists());sequence.refresh_from_db();self.assertEqual(sequence.nextSequence,3)
  sequence.prefix='VND';sequence.padding=8;sequence.save();self.assertEqual(e.Supplier.objects.create(organization=self.org,name='After configuration').code,'VND-00000003')
 def test_backfill_is_controlled_and_idempotent(self):
  e.Supplier.objects.filter(organization=self.org).delete();obj=e.Supplier.objects.create(organization=self.org,name='Missing',code='LEGACY');e.Supplier.objects.filter(pk=obj.pk).update(code='')
  out=StringIO();call_command('backfill_identifiers',organization_id=self.org.pk,stdout=out);obj.refresh_from_db();self.assertEqual(obj.code,'')
  call_command('backfill_identifiers',organization_id=self.org.pk,apply=True,stdout=out);obj.refresh_from_db();code=obj.code
  call_command('backfill_identifiers',organization_id=self.org.pk,apply=True,stdout=out);obj.refresh_from_db();self.assertEqual(obj.code,code)
 def test_initial_salary_and_shift_are_atomic_and_permission_gated(self):
  shift=h.Shift.objects.create(organization=self.org,name='Day',start='09:00',end='17:00')
  payload=dict(name='Setup',phone='5',joiningDate='2024-01-01',designation=self.designation.pk,branch=self.branch.pk,initialShift=shift.pk,initialSalary={'effectiveDate':'2024-01-01','basic':'3100'})
  r=self.api.post('/api/v1/hrms/employees/',payload,format='json');self.assertEqual(r.status_code,201,r.data);self.assertEqual(h.SalaryStructure.objects.get(employee_id=r.data['id']).basic,Decimal('3100'));self.assertTrue(h.ShiftAssignment.objects.filter(employee_id=r.data['id']).exists())
  role=Role.objects.create(organization=self.org,name='Employee creator',scope='organization',permissions=['hrms.employee.create']);UserRoleAssignment.objects.create(user=self.owner,role=role)
  payload['name']='Blocked setup';r=self.api.post('/api/v1/hrms/employees/',payload,format='json');self.assertEqual(r.status_code,403,r.data);self.assertFalse(h.Employee.objects.filter(name='Blocked setup').exists())
 def test_employee_link_populates_and_prevents_duplicates(self):
  data=self.employee();role=Role.objects.create(organization=self.org,name='Login role',scope='own',permissions=['hrms.employee.view'])
  payload={'employee':data['id'],'username':'linked_person','password':'Strong-Test-382!','roles':[role.pk],'branches':[self.branch.pk],'name':'Wrong','email':'wrong@example.com'}
  r=self.api.post('/api/v1/access/users/',payload,format='json');self.assertEqual(r.status_code,201,r.data);self.assertEqual(r.data['name'],'Person');self.assertEqual(r.data['email'],'person@example.com');self.assertEqual(r.data['employee'],data['id'])
  payload['username']='duplicate_person';r=self.api.post('/api/v1/access/users/',payload,format='json');self.assertEqual(r.status_code,400,r.data);self.assertFalse(get_user_model().objects.filter(username='duplicate_person').exists())
  self.api.patch(f'/api/v1/hrms/employees/{data["id"]}/',{'name':'New contact','phone':'999'},format='json');user=get_user_model().objects.get(username='linked_person');self.assertEqual(user.first_name,'New contact');self.assertEqual(user.phone,'999')
  profile=self.api.get(f'/api/v1/hrms/employees/{data["id"]}/').data;self.assertEqual(profile['account']['username'],'linked_person');self.assertNotIn('password',profile['account'])
 def test_employee_options_are_branch_scoped_and_searchable(self):
  own=self.employee();remote=e.Location.objects.create(organization=self.org,name='Remote',kind='Branch');foreign=h.Employee.objects.create(organization=self.org,name='Remote person',phone='5',joiningDate=date(2024,1,1),designation=self.designation,branch=remote)
  role=Role.objects.create(organization=self.org,name='Scoped admin',scope='branches',permissions=['access.users.manage']);UserRoleAssignment.objects.create(user=self.owner,role=role);UserBranchAssignment.objects.create(user=self.owner,branch=self.branch)
  r=self.api.get('/api/v1/access/employee-options/?search=person@example.com');self.assertEqual(r.status_code,200,r.data);self.assertEqual([x['id'] for x in r.data['results']],[own['id']])
  r=self.api.get('/api/v1/access/employee-options/?search=Remote');self.assertEqual(r.data['count'],0)
 def test_designation_code_description_and_create_permission(self):
  r=self.api.post('/api/v1/hrms/designations/',{'name':'Inline designation','description':'Team lead'},format='json');self.assertEqual(r.status_code,201,r.data);self.assertRegex(r.data['code'],r'^DSG-\d{6}$')
  role=Role.objects.create(organization=self.org,name='Read designations',scope='organization',permissions=['hrms.designation.view']);UserRoleAssignment.objects.create(user=self.owner,role=role)
  r=self.api.post('/api/v1/hrms/designations/',{'name':'Blocked'},format='json');self.assertEqual(r.status_code,403)
 def test_document_year_scopes_and_external_values(self):
  a=allocate(self.org,'test.invoice','INV',True,day=date(2025,1,1));b=allocate(self.org,'test.invoice','INV',True,day=date(2026,1,1));self.assertEqual(a,'INV-2025-000001');self.assertEqual(b,'INV-2026-000001')
  c=allocate(self.org,'test.invoice','INV',True,day=date(2025,2,1));self.assertEqual(c,'INV-2025-000002')
  expense=e.Expense.objects.create(organization=self.org,date=date(2024,1,1),category='Office',description='Office costs',amount=1);self.assertRegex(expense.reference,r'^EXP-2024-\d{6}$')
  entry=e.LedgerEntry.objects.create(organization=self.org,date=date(2024,1,1),account='Cash',type='Inflow',description='Income',amount=1);self.assertRegex(entry.reference,r'^INC-2024-\d{6}$')

@skipUnless(connection.vendor=='postgresql','PostgreSQL row-lock concurrency verification requires PostgreSQL')
class ConcurrentCodes(TransactionTestCase):
 def test_simultaneous_api_requests(self):
  org=Organization.objects.create(name='Concurrent API numbering')
  user=get_user_model().objects.create_user(username='concurrent_api_owner',organization=org,role='owner')
  def create(index):
   close_old_connections()
   try:
    api=APIClient();api.force_authenticate(get_user_model().objects.get(pk=user.pk))
    response=api.post('/api/v1/suppliers/',{'name':f'API vendor {index}'},format='json')
    self.assertEqual(response.status_code,201,response.data)
    return response.data['code']
   finally:close_old_connections()
  with ThreadPoolExecutor(max_workers=8) as pool:codes=list(pool.map(create,range(16)))
  self.assertEqual(len(codes),len(set(codes)))
  self.assertEqual(sorted(codes),[f'SUP-{n:06}' for n in range(1,17)])
 def test_parallel_allocations_on_first_sequence_row(self):
  org=Organization.objects.create(name='Concurrent numbering')
  def create(index):
   close_old_connections()
   try:return e.Supplier.objects.create(organization_id=org.pk,name=f'Concurrent {index}').code
   finally:close_old_connections()
  with ThreadPoolExecutor(max_workers=8) as pool:codes=list(pool.map(create,range(16)))
  self.assertEqual(len(codes),len(set(codes)));self.assertEqual(sorted(codes),[f'SUP-{n:06}' for n in range(1,17)])
