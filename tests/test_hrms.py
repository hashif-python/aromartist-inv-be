from datetime import date,datetime,time,timedelta
from decimal import Decimal
from tempfile import TemporaryDirectory
from django.test import TestCase,override_settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from django.core.management import call_command
from rest_framework.test import APIClient
from apps.accounts.models import Organization,Role,UserRoleAssignment,UserBranchAssignment
from apps.erp import models as e
from apps.hrms import models as m,services as s
class HRMS(TestCase):
 def setUp(self):
  self.org=Organization.objects.create(name='HR Shop');self.other=Organization.objects.create(name='Other')
  self.owner=get_user_model().objects.create_user(username='hr_owner',password='Secure-pass-843!',organization=self.org,role='owner')
  self.wh=e.Location.objects.create(organization=self.org,name='Warehouse',code='WH',kind='Warehouse')
  self.branch=e.Location.objects.create(organization=self.org,name='Shop',code='BR',kind='Branch',warehouse=self.wh)
  self.branch2=e.Location.objects.create(organization=self.org,name='Remote',code='BR2',kind='Branch')
  self.dep=m.Department.objects.create(organization=self.org,name='Retail');self.des=m.Designation.objects.create(organization=self.org,name='Sales',department=self.dep)
  self.user=get_user_model().objects.create_user(username='employee',password='Secure-pass-843!',organization=self.org,role='staff')
  self.emp=m.Employee.objects.create(organization=self.org,name='Employee',employeeCode='E01',phone='555',joiningDate=date(2024,1,1),department=self.dep,designation=self.des,branch=self.branch,user=self.user)
  self.emp2=m.Employee.objects.create(organization=self.org,name='Other Employee',employeeCode='E02',phone='556',joiningDate=date(2024,1,1),department=self.dep,designation=self.des,branch=self.branch2)
  self.shift=m.Shift.objects.create(organization=self.org,name='Day',start=time(9),end=time(17),breakMinutes=60,weeklyOff=[6],overtimeEnabled=True,graceMinutes=10)
  m.ShiftAssignment.objects.create(organization=self.org,employee=self.emp,shift=self.shift,effectiveDate=date(2024,1,1))
  self.type=m.LeaveType.objects.create(organization=self.org,name='Annual',paid=True,annualDays=12)
  self.api=APIClient();self.api.force_authenticate(self.owner)
 def role(self,user,codes,scope='own',branches=[]):
  user.roleAssignments.all().delete();role=Role.objects.create(organization=self.org,name=f'Role-{Role.objects.count()}',permissions=codes,scope=scope);UserRoleAssignment.objects.create(user=user,role=role)
  for branch in branches:UserBranchAssignment.objects.get_or_create(user=user,branch=branch)
  return role
 def post(self,route,data={},expected=201):
  r=self.api.post('/api/v1/'+route,data,format='json');self.assertEqual(r.status_code,expected,getattr(r,'data',None));return r
 def record(self,model,**kw):return model.objects.create(organization=self.org,**kw)
 def payroll(self,joining=None):
  if joining:self.emp.joiningDate=joining;self.emp.save()
  period=self.record(m.PayrollPeriod,year=2024,month=1)
  self.record(m.SalaryStructure,employee=self.emp,effectiveDate=date(2024,1,1),basic=3100,allowances=0,deductions=0,overtimeHourly=60)
  for day in s.days(max(date(2024,1,1),self.emp.joiningDate),date(2024,1,31)):
   if not s.off_day(self.emp,day):self.record(m.Attendance,employee=self.emp,date=day,status='Present',approved=True)
  return self.record(m.PayrollRecord,employee=self.emp,period=period)
 def test_crud_validation_and_lookup_tenant(self):
  r=self.post('hrms/departments/',{'name':'Warehouse team'});self.assertEqual(r.data['name'],'Warehouse team')
  other=e.Location.objects.create(organization=self.other,name='Wrong',code='W',kind='Branch')
  self.post('hrms/employees/',{'name':'Invalid','employeeCode':'E03','phone':'1','joiningDate':'2024-01-01','department':self.dep.pk,'designation':self.des.pk,'branch':other.pk},400)
  self.post('hrms/shifts/',{'name':'Bad','start':'09:00','end':'17:00','weeklyOff':[7]},400)
 def test_employee_own_read_and_denied_mutation(self):
  self.role(self.user,['hrms.employee.view','hrms.attendance.view','hrms.payroll.view','hrms.document.download'])
  self.api.force_authenticate(self.user)
  r=self.api.get('/api/v1/hrms/employees/');self.assertEqual([x['id'] for x in r.data['results']],[self.emp.pk])
  self.assertEqual(self.api.get(f'/api/v1/hrms/employees/{self.emp2.pk}/').status_code,404)
  self.post('hrms/departments/',{'name':'Denied'},403)
  self.assertEqual(self.api.get('/api/v1/access/users/').status_code,403)
 def test_branch_scope_and_team_scope(self):
  self.role(self.user,['hrms.employee.view'],'branches',[self.branch]);self.api.force_authenticate(self.user)
  r=self.api.get('/api/v1/hrms/employees/');self.assertEqual(r.data['count'],1)
  self.emp2.manager=self.emp;self.emp2.save();self.role(self.user,['hrms.employee.view'],'team')
  self.assertEqual(self.api.get('/api/v1/hrms/employees/').data['count'],2)
 def test_mixed_roles_do_not_broaden_private_documents(self):
  self.role(self.user,['hrms.employee.view'],'own')
  role=Role.objects.create(organization=self.org,name='Finance',scope='organization',permissions=['accounting.ledger.view']);UserRoleAssignment.objects.create(user=self.user,role=role)
  self.api.force_authenticate(self.user);self.assertEqual(self.api.get('/api/v1/hrms/employees/').data['count'],1)
 def test_attendance_metrics_overnight_and_duplicate(self):
  self.shift.start=time(22);self.shift.end=time(6);self.shift.save()
  a=self.record(m.Attendance,employee=self.emp,date=date(2024,1,2),checkIn=timezone.make_aware(datetime(2024,1,2,22,20)),checkOut=timezone.make_aware(datetime(2024,1,3,7)))
  s.attendance_metrics(a);self.assertEqual(a.lateMinutes,10);self.assertEqual(a.overtimeMinutes,60);self.assertEqual(a.workingMinutes,460)
  self.post('hrms/attendance/',{'employee':self.emp.pk,'date':'2024-01-02'},400)
 def test_attendance_checkout_validation(self):
  self.post('hrms/attendance/',{'employee':self.emp.pk,'date':'2024-01-03','checkOut':'2024-01-03T10:00:00Z'},400)
 def test_self_attendance_policy_and_self_approval(self):
  self.role(self.user,['hrms.self_attendance','hrms.attendance.view','hrms.attendance.approve'])
  self.api.force_authenticate(self.user)
  self.post('hrms/attendance/check_in/',{'employee':self.emp.pk},403)
  self.record(m.Policy,selfAttendance=True)
  self.post('hrms/attendance/check_in/',{'employee':self.emp.pk},200)
  self.post('hrms/attendance/check_in/',{'employee':self.emp.pk},400)
  row=m.Attendance.objects.get(employee=self.emp,date=timezone.localdate())
  self.post(f'hrms/attendance/{row.pk}/approve/',{},403)
  self.post('hrms/attendance/check_out/',{'employee':self.emp.pk},200)
 def test_leave_approve_balance_overlap_and_cancel(self):
  r=self.post('hrms/leaves/',{'employee':self.emp.pk,'leaveType':self.type.pk,'startDate':'2024-01-02','endDate':'2024-01-03','reason':'Family'})
  self.post('hrms/leaves/',{'employee':self.emp.pk,'leaveType':self.type.pk,'startDate':'2024-01-03','endDate':'2024-01-04','reason':'Overlap'},400)
  self.post(f'hrms/leaves/{r.data["id"]}/approve/',{},200);self.post(f'hrms/leaves/{r.data["id"]}/approve/',{},200)
  self.assertEqual(m.LeaveBalance.objects.get(employee=self.emp).used,2)
  self.post(f'hrms/leaves/{r.data["id"]}/cancel/',{},200);self.assertEqual(m.LeaveBalance.objects.get(employee=self.emp).used,0)
 def test_leave_insufficient_balance_self_approval(self):
  self.type.annualDays=0;self.type.save()
  r=self.post('hrms/leaves/',{'employee':self.emp.pk,'leaveType':self.type.pk,'startDate':'2024-01-02','endDate':'2024-01-02','reason':'Test'})
  self.post(f'hrms/leaves/{r.data["id"]}/approve/',{},400)
  self.role(self.user,['hrms.leave.approve']);self.api.force_authenticate(self.user);self.post(f'hrms/leaves/{r.data["id"]}/approve/',{},403)
 def test_payroll_full_month_payment_idempotent_and_locks(self):
  p=self.payroll();p=s.calculate(self.owner,p);self.assertEqual(p.net,3100)
  p=s.payroll_action(self.owner,p,'approve');s.payroll_action(self.owner,p,'approve');self.assertEqual(e.Expense.objects.filter(category='Payroll').count(),1)
  s.payroll_action(self.owner,p,'pay');s.payroll_action(self.owner,p,'pay');self.assertEqual(e.LedgerEntry.objects.filter(source='payroll').count(),1)
  self.assertEqual(e.Expense.objects.get(category='Payroll').amount,3100)
  self.post('hrms/attendance/',{'employee':self.emp.pk,'date':'2024-01-01'},400)
  self.assertEqual(self.api.patch(f'/api/v1/hrms/payroll/{p.pk}/',{'net':1},format='json').status_code,400)
 def test_payroll_missing_attendance_blocks(self):
  p=self.payroll();m.Attendance.objects.filter(employee=self.emp,date=date(2024,1,2)).delete()
  self.post(f'hrms/payroll/{p.pk}/calculate/',{},400)
 def test_payroll_proration_revision_half_day_absence_and_overtime(self):
  p=self.payroll(joining=date(2024,1,16));self.record(m.SalaryStructure,employee=self.emp,effectiveDate=date(2024,1,21),basic=6200,overtimeHourly=60)
  m.Attendance.objects.filter(employee=self.emp,date=date(2024,1,16)).update(status='Half Day')
  m.Attendance.objects.filter(employee=self.emp,date=date(2024,1,17)).update(status='Absent')
  m.Attendance.objects.filter(employee=self.emp,date=date(2024,1,18)).update(overtimeMinutes=60)
  p=s.calculate(self.owner,p);self.assertEqual(p.earned,2610);self.assertEqual(Decimal(p.snapshot['overtime']),60)
 def test_unpaid_leave_deducts_and_holiday_paid(self):
  p=self.payroll();unpaid=self.record(m.LeaveType,name='Unpaid',paid=False)
  leave=self.record(m.LeaveRequest,employee=self.emp,leaveType=unpaid,startDate=date(2024,1,2),endDate=date(2024,1,3),days=2,reason='Test');s.leave_action(self.owner,leave,'approve')
  self.record(m.Holiday,name='Festival',date=date(2024,1,4));m.Attendance.objects.filter(employee=self.emp,date=date(2024,1,4)).delete()
  p=s.calculate(self.owner,p);self.assertEqual(p.net,2900)
 def test_advance_recovery_accounting_and_remaining(self):
  p=self.payroll();a=self.record(m.SalaryAdvance,employee=self.emp,date=date(2024,1,1),deductionFrom=date(2024,1,1),amount=800,installment=300,reason='Advance')
  s.advance_action(self.owner,a,'approve');a=s.advance_action(self.owner,a,'disburse');s.advance_action(self.owner,a,'disburse');self.assertEqual(e.LedgerEntry.objects.filter(source='salary_advance').count(),1)
  p=s.calculate(self.owner,p);self.assertEqual(p.advanceDeduction,300);self.assertEqual(p.net,2800)
  s.payroll_action(self.owner,p,'approve');s.payroll_action(self.owner,p,'approve');a.refresh_from_db();self.assertEqual(a.repaid,300);self.assertEqual(m.AdvanceRepayment.objects.count(),1);self.assertEqual(e.Expense.objects.get().amount,3100)
 def test_salary_revision_effective_history_and_self_denied(self):
  self.record(m.SalaryStructure,employee=self.emp,effectiveDate=date(2024,1,1),basic=3000)
  revision=self.record(m.SalaryRevision,employee=self.emp,effectiveDate=date(2024,2,1),revisedSalary=3500,reason='Review')
  s.revision_approve(self.owner,revision);s.revision_approve(self.owner,revision);self.assertEqual(m.SalaryStructure.objects.filter(employee=self.emp).count(),2);revision.refresh_from_db();self.assertEqual(revision.previousSalary,3000)
 def test_no_self_payroll_or_advance_approval(self):
  p=self.payroll();s.calculate(self.owner,p);self.role(self.user,['hrms.payroll.approve','hrms.advance.approve']);self.api.force_authenticate(self.user)
  self.post(f'hrms/payroll/{p.pk}/approve/',{},403)
  a=self.record(m.SalaryAdvance,employee=self.emp,date=date(2024,1,1),deductionFrom=date(2024,1,1),amount=10,installment=10,reason='Test')
  self.post(f'hrms/salary-advances/{a.pk}/approve/',{},403)
 def test_secure_document_upload_download_and_cross_employee(self):
  with TemporaryDirectory() as directory,override_settings(MEDIA_ROOT=directory):
   file=SimpleUploadedFile('identity.pdf',b'%PDF-1.4 test',content_type='application/pdf')
   r=self.api.post('/api/v1/hrms/documents/',{'employee':self.emp.pk,'name':'Identity','documentType':'Identity','file':file},format='multipart');self.assertEqual(r.status_code,201,r.data);self.assertNotIn('file',r.data)
   self.assertEqual(self.api.get(f'/api/v1/hrms/documents/{r.data["id"]}/download/').status_code,200)
   self.role(self.user,['hrms.document.download']);self.api.force_authenticate(self.user)
   self.assertEqual(self.api.get(f'/api/v1/hrms/documents/{r.data["id"]}/download/').status_code,200)
   document=self.record(m.EmployeeDocument,employee=self.emp2,name='Other identity',documentType='Identity',file='private_hr/other.pdf')
   self.assertEqual(self.api.get(f'/api/v1/hrms/documents/{document.pk}/download/').status_code,404)
 def test_upload_invalid_file_rejected(self):
  file=SimpleUploadedFile('shell.exe',b'MZ executable',content_type='application/octet-stream')
  r=self.api.post('/api/v1/hrms/documents/',{'employee':self.emp.pk,'name':'Bad','documentType':'Other','file':file},format='multipart');self.assertEqual(r.status_code,400)
 def test_payslip_and_certificates(self):
  p=self.payroll();s.calculate(self.owner,p);s.payroll_action(self.owner,p,'approve')
  response=self.api.get(f'/api/v1/hrms/payroll/{p.pk}/payslip/');self.assertEqual(response.status_code,200);self.assertTrue(b''.join(response.streaming_content).startswith(b'%PDF'))
  r=self.api.get('/api/v1/hrms/documents/certificate/',{'employee':self.emp.pk,'type':'Employment Certificate'});self.assertEqual(r.status_code,200)
 def test_role_escalation_and_branch_boundaries(self):
  self.role(self.user,['access.roles.manage','access.users.manage','hrms.employee.view'],'branches',[self.branch]);self.api.force_authenticate(self.user)
  self.post('access/roles/',{'name':'Escalate','scope':'organization','permissions':['*']},403)
  self.post('access/roles/',{'name':'Escalate scope','scope':'organization','permissions':['hrms.employee.view']},403)
  self.assertEqual(self.api.patch(f'/api/v1/access/users/{self.owner.pk}/',{'is_active':False},format='json').status_code,404)
 def test_user_provisioning_password_hash_roles_and_employee_link(self):
  role=Role.objects.create(organization=self.org,name='Employee role',scope='own',permissions=['hrms.employee.view'])
  self.post('access/users/',{'username':'new_staff','name':'New Staff','password':'Good-long-password-389!','roles':[role.pk],'branches':[],'employee':self.emp2.pk})
  u=get_user_model().objects.get(username='new_staff');self.assertTrue(u.check_password('Good-long-password-389!'));self.emp2.refresh_from_db();self.assertEqual(self.emp2.user,u);self.assertFalse(u.is_superuser)
 def test_migration_bootstrap_preserves_users_and_roles(self):
  call_command('bootstrap_access');role=self.user.roleAssignments.get().role;self.assertEqual(role.name,'Legacy Staff');self.assertNotIn('*',role.permissions)
  call_command('bootstrap_access');self.assertEqual(self.user.roleAssignments.count(),1)
 def test_granular_erp_action_and_dashboard_leak(self):
  self.role(self.user,['inventory.raw_material.view'],'branches',[self.branch]);self.api.force_authenticate(self.user)
  self.assertEqual(self.api.get('/api/v1/inventory/raw-materials/').status_code,200)
  self.post('inventory/raw-materials/',{'name':'No permission'},403)
  self.assertEqual(self.api.get('/api/v1/sales/invoices/').status_code,403)
  r=self.api.get('/api/v1/dashboard/summary/');self.assertEqual(r.status_code,200);self.assertNotIn('todaySales',r.data['kpis']);self.assertEqual(r.data['salesTrend'],[])

 def test_unpaid_leave_does_not_deduct_weekly_off(self):
  p=self.payroll();typ=self.record(m.LeaveType,name='Unpaid weekend',paid=False)
  leave=self.record(m.LeaveRequest,employee=self.emp,leaveType=typ,startDate=date(2024,1,6),endDate=date(2024,1,8),days=2,reason='Weekend');s.leave_action(self.owner,leave,'approve')
  p=s.calculate(self.owner,p);self.assertEqual(p.net,2900)
 def test_read_only_attendance_edit_revokes_approval(self):
  row=self.record(m.Attendance,employee=self.emp,date=date(2024,1,2),approved=True)
  self.role(self.user,['hrms.attendance.edit'],'branches',[self.branch]);self.api.force_authenticate(self.user)
  response=self.api.patch(f'/api/v1/hrms/attendance/{row.pk}/',{'notes':'Correction'},format='json');self.assertEqual(response.status_code,200,response.data);row.refresh_from_db();self.assertFalse(row.approved)
 def test_document_export_is_scoped_and_contains_no_file_path(self):
  self.record(m.EmployeeDocument,employee=self.emp,name='Own',documentType='Identity',file='private_hr/own.pdf')
  self.record(m.EmployeeDocument,employee=self.emp2,name='Other',documentType='Identity',file='private_hr/other.pdf')
  self.role(self.user,['hrms.document.export']);self.api.force_authenticate(self.user)
  response=self.api.get('/api/v1/hrms/documents/export/');self.assertEqual(response.status_code,200);content=response.content.decode();self.assertIn('Own',content);self.assertNotIn('Other',content);self.assertNotIn('private_hr',content)
 def test_custom_roles_cannot_modify_self_or_last_admin(self):
  call_command('bootstrap_access');self.api.force_authenticate(self.owner)
  role=self.owner.roleAssignments.get().role
  self.assertEqual(self.api.patch(f'/api/v1/access/roles/{role.pk}/',{'permissions':[]},format='json').status_code,403)
  self.assertEqual(self.api.patch(f'/api/v1/access/users/{self.owner.pk}/',{'is_active':False},format='json').status_code,403)
 def test_department_and_designation_edit_delete(self):
  department=self.post('hrms/departments/',{'name':'New Department'}).data
  designation=self.post('hrms/designations/',{'name':'New Designation','department':department['id']}).data
  response=self.api.patch(f'/api/v1/hrms/designations/{designation["id"]}/',{'name':'Edited Designation'},format='json');self.assertEqual(response.status_code,200,response.data)
  self.assertEqual(self.api.delete(f'/api/v1/hrms/designations/{designation["id"]}/').status_code,204)
  self.assertEqual(self.api.delete(f'/api/v1/hrms/departments/{department["id"]}/').status_code,204)
 def test_invalid_filters_are_validation_errors(self):
  self.assertEqual(self.api.get('/api/v1/hrms/payroll-periods/?year=invalid').status_code,400)
  self.assertEqual(self.api.get('/api/v1/hrms/attendance/?date=invalid').status_code,400)
 def test_sales_template_keeps_private_hr_in_separate_role(self):
  call_command('bootstrap_access');role=Role.objects.get(organization=self.org,name='Sales Executive')
  self.assertFalse(any(p.startswith('hrms.') for p in role.permissions))
 def test_openapi_includes_hrms_and_access_for_anonymous_docs(self):
  self.api.force_authenticate(None)
  response=self.api.get('/api/schema/?format=json')
  self.assertEqual(response.status_code,200)
  self.assertIn('/api/v1/hrms/payroll/',response.data['paths'])
  self.assertIn('/api/v1/access/roles/',response.data['paths'])
 def test_profile_activity_respects_resource_permissions_and_employee_scope(self):
  self.post('hrms/leaves/',{'employee':self.emp.pk,'leaveType':self.type.pk,'startDate':'2024-01-02','endDate':'2024-01-02','reason':'Test activity'})
  rows=self.api.get(f'/api/v1/hrms/employees/{self.emp.pk}/activity/').data['results'];self.assertEqual(len(rows),1);self.assertEqual(rows[0]['resource'],'leave')
  self.role(self.user,['hrms.employee.view'],'own');self.api.force_authenticate(self.user)
  self.assertEqual(self.api.get(f'/api/v1/hrms/employees/{self.emp.pk}/activity/').data['results'],[])
  self.assertEqual(self.api.get(f'/api/v1/hrms/employees/{self.emp2.pk}/activity/').status_code,404)
 def test_period_close_requires_paid_records_and_locks_new_entries(self):
  pay=self.payroll();url=f'/api/v1/hrms/payroll-periods/{pay.period_id}/close/'
  self.assertEqual(self.api.post(url,{},format='json').status_code,400)
  s.calculate(self.owner,pay);s.payroll_action(self.owner,pay,'approve');s.payroll_action(self.owner,pay,'pay','Bank')
  response=self.api.post(url,{},format='json');self.assertEqual(response.status_code,200,response.data);self.assertTrue(response.data['closed'])
  self.post('hrms/payroll/',{'employee':self.emp2.pk,'period':pay.period_id},400)
  self.post('hrms/attendance/',{'employee':self.emp2.pk,'date':'2024-01-02','status':'Present'},400)
  self.assertEqual(self.api.patch(f'/api/v1/hrms/payroll-periods/{pay.period_id}/',{'month':2},format='json').status_code,400)
 def test_leave_date_range_overlap_filter(self):
  self.post('hrms/leaves/',{'employee':self.emp.pk,'leaveType':self.type.pk,'startDate':'2024-01-02','endDate':'2024-01-04','reason':'Range'})
  self.assertEqual(self.api.get('/api/v1/hrms/leaves/?fromDate=2024-01-03&toDate=2024-01-03').data['count'],1)
  self.assertEqual(self.api.get('/api/v1/hrms/leaves/?fromDate=2024-01-05').data['count'],0)
 def test_document_issue_expiry_validation_and_status(self):
  with TemporaryDirectory() as folder,override_settings(MEDIA_ROOT=folder):
   doc=SimpleUploadedFile('valid.pdf',b'%PDF-1.4\n%%EOF',content_type='application/pdf')
   response=self.api.post('/api/v1/hrms/documents/',{'employee':self.emp.pk,'name':'Passport','documentType':'Passport','file':doc,'issueDate':'2024-02-01','expiryDate':'2024-01-01'},format='multipart');self.assertEqual(response.status_code,400)
   doc=SimpleUploadedFile('valid.pdf',b'%PDF-1.4\n%%EOF',content_type='application/pdf')
   response=self.api.post('/api/v1/hrms/documents/',{'employee':self.emp.pk,'name':'Passport','documentType':'Passport','file':doc,'issueDate':'2023-02-01','expiryDate':'2024-01-01'},format='multipart');self.assertEqual(response.status_code,201,response.data);self.assertEqual(response.data['status'],'Expired')
 def test_balance_adjustment_activity_retains_before_and_after(self):
  response=self.post('hrms/leave-balances/',{'employee':self.emp.pk,'leaveType':self.type.pk,'year':2024,'entitlement':'12'})
  response=self.api.patch(f'/api/v1/hrms/leave-balances/{response.data["id"]}/',{'entitlement':'15'},format='json');self.assertEqual(response.status_code,200,response.data)
  event=m.HRActivity.objects.filter(employee=self.emp,resource='leave_balance',action='partial_update').get()
  self.assertEqual(Decimal(event.details['before']['entitlement']),Decimal('12'));self.assertEqual(Decimal(event.details['after']['entitlement']),Decimal('15'))
