"""PostgreSQL-only concurrent posting checks (SQLite has no row-lock semantics)."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from unittest import skipUnless
from django.db import connection,close_old_connections
from django.test import TransactionTestCase
from django.contrib.auth import get_user_model
from apps.accounts.models import Organization
from apps.erp import models as e
from apps.hrms import models as m,services as s
@skipUnless(connection.vendor=='postgresql','Run with PostgreSQL for real row-lock concurrency checks.')
class ConcurrentPayroll(TransactionTestCase):
 def setUp(self):
  self.org=Organization.objects.create(name='Concurrent HR')
  self.user=get_user_model().objects.create_user(username='concurrent_owner',organization=self.org,role='owner')
  branch=e.Location.objects.create(organization=self.org,name='Branch',code='B',kind='Branch')
  dep=m.Department.objects.create(organization=self.org,name='Sales');des=m.Designation.objects.create(organization=self.org,name='Clerk')
  self.employee=m.Employee.objects.create(organization=self.org,name='Employee',employeeCode='C1',phone='1',department=dep,designation=des,branch=branch,joiningDate=date(2024,1,1))
  m.SalaryStructure.objects.create(organization=self.org,employee=self.employee,effectiveDate=date(2024,1,1),basic=3100)
  for day in range(1,32):m.Attendance.objects.create(organization=self.org,employee=self.employee,date=date(2024,1,day),status='Present',approved=True)
  period=m.PayrollPeriod.objects.create(organization=self.org,year=2024,month=1)
  self.pay=m.PayrollRecord.objects.create(organization=self.org,employee=self.employee,period=period);s.calculate(self.user,self.pay)
 def concurrent(self,action):
  uid=self.user.pk;pid=self.pay.pk
  def post(_):
   close_old_connections()
   try:return s.payroll_action(get_user_model().objects.get(pk=uid),m.PayrollRecord.objects.get(pk=pid),action).status
   finally:close_old_connections()
  with ThreadPoolExecutor(max_workers=2) as executor:return list(executor.map(post,[1,2]))
 def test_concurrent_approval_posts_one_expense(self):
  self.assertEqual(self.concurrent('approve'),['Approved','Approved']);self.assertEqual(e.Expense.objects.filter(category='Payroll').count(),1)
 def test_concurrent_payment_posts_one_outflow(self):
  s.payroll_action(self.user,self.pay,'approve');self.assertEqual(self.concurrent('pay'),['Paid','Paid']);self.assertEqual(e.LedgerEntry.objects.filter(source='payroll').count(),1)
