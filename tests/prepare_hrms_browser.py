"""Opt-in isolated browser fixture. Run only using config.settings.test and a scratch SQLite file."""
import os,sys,calendar
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import django
django.setup()
from django.conf import settings
if os.environ.get('DJANGO_SETTINGS_MODULE')!='config.settings.test' or settings.DATABASES['default']['NAME']==':memory:':raise RuntimeError('Use test settings and a scratch SQLITE_TEST_DATABASE file.')
from django.contrib.auth import get_user_model
from django.core.management import call_command
from apps.accounts.models import Organization,Role,UserRoleAssignment
from apps.erp.models import Location
from apps.hrms import models as m
from datetime import date,time
org,_=Organization.objects.get_or_create(name='HRMS Browser Verification')
password=os.environ['E2E_PASSWORD']
owner,_=get_user_model().objects.get_or_create(username='hrms_browser',defaults={'organization':org,'role':'owner'})
if owner.organization!=org:raise RuntimeError('Fixture username belongs to a different organization.')
owner.set_password(password);owner.save();call_command('bootstrap_access')
branch,_=Location.objects.get_or_create(organization=org,code='BR-E2E',defaults={'name':'Test Branch','kind':'Branch'})
dep,_=m.Department.objects.get_or_create(organization=org,name='Test Sales')
des,_=m.Designation.objects.get_or_create(organization=org,name='Test Executive',defaults={'department':dep})
user,_=get_user_model().objects.get_or_create(username='hrms_employee',defaults={'organization':org,'role':'staff'})
user.set_password(password);user.save()
role=Role.objects.get(organization=org,name='Employee');user.roleAssignments.all().delete();UserRoleAssignment.objects.create(user=user,role=role)
emp,_=m.Employee.objects.get_or_create(organization=org,employeeCode='E2E01',defaults={'name':'Browser Employee','phone':'555123456','joiningDate':date(2024,1,1),'department':dep,'designation':des,'branch':branch,'user':user})
shift,_=m.Shift.objects.get_or_create(organization=org,name='Test Day Shift',defaults={'start':time(9),'end':time(17),'weeklyOff':[6]})
m.ShiftAssignment.objects.get_or_create(organization=org,employee=emp,effectiveDate=date(2024,1,1),defaults={'shift':shift})
m.LeaveType.objects.get_or_create(organization=org,name='Annual Test',defaults={'paid':True,'annualDays':12})
m.SalaryStructure.objects.get_or_create(organization=org,employee=emp,effectiveDate=date(2024,1,1),defaults={'basic':3100})
for day in range(1,32):m.Attendance.objects.get_or_create(organization=org,employee=emp,date=date(2024,1,day),defaults={'status':'Present','approved':True})
m.PayrollPeriod.objects.get_or_create(organization=org,year=2024,month=1)
print('Isolated browser fixture ready.')
