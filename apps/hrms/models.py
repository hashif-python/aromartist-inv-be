from django.db import models
from django.db.models import Q
from apps.erp.models import TenantModel,Master,relation,money
class Department(Master):
 description=models.TextField(blank=True)
 class Meta: constraints=[models.UniqueConstraint(fields=['organization','name'],name='hr_department_name')]
class Designation(Master):
 code=models.CharField(max_length=60,blank=True)
 description=models.TextField(blank=True)
 department=relation(Department,null=True,blank=True)
 class Meta: constraints=[models.UniqueConstraint(fields=['organization','name'],name='hr_designation_name'),models.UniqueConstraint(fields=['organization','code'],condition=~Q(code=''),name='hr_designation_code')]
class Shift(Master):
 start=models.TimeField();end=models.TimeField()
 breakMinutes=models.PositiveIntegerField(default=0)
 weeklyOff=models.JSONField(default=list)
 graceMinutes=models.PositiveIntegerField(default=10)
 overtimeEnabled=models.BooleanField(default=False)
class Policy(TenantModel):
 selfAttendance=models.BooleanField(default=False)
 class Meta: constraints=[models.UniqueConstraint(fields=['organization'],name='hr_policy_org')]
class Employee(Master):
 employeeCode=models.CharField(max_length=60)
 phone=models.CharField(max_length=40);email=models.EmailField(blank=True)
 dateOfBirth=models.DateField(null=True,blank=True);gender=models.CharField(max_length=30,blank=True)
 joiningDate=models.DateField();leavingDate=models.DateField(null=True,blank=True)
 department=relation(Department,null=True,blank=True);designation=relation(Designation)
 branch=relation('erp.Location')
 manager=relation('self',null=True,blank=True,related_name='team')
 employmentType=models.CharField(max_length=30,choices=[(v,v) for v in ['Full Time','Part Time','Contract']],default='Full Time')
 emergencyContact=models.CharField(max_length=200,blank=True);address=models.TextField(blank=True)
 user=relation('accounts.User',null=True,blank=True,related_name='employees')
 class Meta: constraints=[models.UniqueConstraint(fields=['organization','employeeCode'],name='hr_employee_code'),models.UniqueConstraint(fields=['organization','user'],condition=Q(user__isnull=False),name='hr_employee_user')]
class ShiftAssignment(TenantModel):
 employee=relation(Employee);shift=relation(Shift);effectiveDate=models.DateField()
 class Meta: constraints=[models.UniqueConstraint(fields=['employee','effectiveDate'],name='hr_shift_date')]
class Attendance(TenantModel):
 employee=relation(Employee);date=models.DateField()
 status=models.CharField(max_length=20,choices=[(v,v) for v in ['Present','Absent','Half Day','Leave','Holiday','Weekly Off']],default='Present')
 checkIn=models.DateTimeField(null=True,blank=True);checkOut=models.DateTimeField(null=True,blank=True)
 workingMinutes=models.PositiveIntegerField(default=0);lateMinutes=models.PositiveIntegerField(default=0);earlyMinutes=models.PositiveIntegerField(default=0);overtimeMinutes=models.PositiveIntegerField(default=0)
 approved=models.BooleanField(default=False);notes=models.TextField(blank=True)
 recordedBy=relation('accounts.User',null=True,blank=True,related_name='+')
 class Meta:
  constraints=[models.UniqueConstraint(fields=['employee','date'],name='hr_daily_attendance')]
  indexes=[models.Index(fields=['organization','date','status'],name='hr_attendance_day')]
class Holiday(Master):
 date=models.DateField();branch=relation('erp.Location',null=True,blank=True)
 holidayType=models.CharField(max_length=40,default='Public',choices=[(v,v) for v in ['Public','Company','Optional']])
class LeaveType(Master):
 paid=models.BooleanField(default=True)
 annualDays=models.DecimalField(max_digits=6,decimal_places=2,default=0)
class LeaveBalance(TenantModel):
 employee=relation(Employee);leaveType=relation(LeaveType);year=models.PositiveIntegerField()
 entitlement=models.DecimalField(max_digits=6,decimal_places=2,default=0)
 used=models.DecimalField(max_digits=6,decimal_places=2,default=0)
 class Meta: constraints=[models.UniqueConstraint(fields=['employee','leaveType','year'],name='hr_leave_balance')]
class LeaveRequest(TenantModel):
 employee=relation(Employee);leaveType=relation(LeaveType);startDate=models.DateField();endDate=models.DateField()
 days=models.DecimalField(max_digits=6,decimal_places=2,default=0);reason=models.TextField()
 status=models.CharField(max_length=20,default='Pending')
 approvedBy=relation('accounts.User',null=True,blank=True,related_name='+')
class SalaryStructure(TenantModel):
 employee=relation(Employee);effectiveDate=models.DateField()
 basic=money();allowances=money();deductions=money();overtimeHourly=money()
 reason=models.TextField(blank=True)
 approvedBy=relation('accounts.User',null=True,blank=True,related_name='+')
 class Meta: constraints=[models.UniqueConstraint(fields=['employee','effectiveDate'],name='hr_salary_date')]
class SalaryRevision(TenantModel):
 employee=relation(Employee);effectiveDate=models.DateField()
 previousSalary=money();revisedSalary=money();allowances=money();deductions=money();overtimeHourly=money()
 reason=models.TextField();approvedBy=relation('accounts.User',null=True,blank=True,related_name='+')
 status=models.CharField(max_length=20,default='Pending')
class PayrollPeriod(TenantModel):
 closed=models.BooleanField(default=False)
 year=models.PositiveIntegerField();month=models.PositiveSmallIntegerField()
 class Meta: constraints=[models.UniqueConstraint(fields=['organization','year','month'],name='hr_payroll_period')]
class PayrollRecord(TenantModel):
 employee=relation(Employee);period=relation(PayrollPeriod)
 status=models.CharField(max_length=20,default='Draft')
 earned=money();advanceDeduction=money();net=money()
 snapshot=models.JSONField(default=dict)
 approvedBy=relation('accounts.User',null=True,blank=True,related_name='+');paidBy=relation('accounts.User',null=True,blank=True,related_name='+')
 paidDate=models.DateField(null=True,blank=True);paymentMethod=models.CharField(max_length=30,blank=True)
 expense=relation('erp.Expense',null=True,blank=True)
 class Meta:
  constraints=[models.UniqueConstraint(fields=['employee','period'],name='hr_payroll_unique')]
  indexes=[models.Index(fields=['organization','status'],name='hr_payroll_status')]
class PayrollComponent(TenantModel):
 payroll=relation(PayrollRecord);name=models.CharField(max_length=100);amount=money()
class SalaryAdvance(TenantModel):
 employee=relation(Employee);date=models.DateField();amount=money();reason=models.TextField()
 installment=money();deductionFrom=models.DateField()
 repaid=money();status=models.CharField(max_length=20,default='Pending')
 approvedBy=relation('accounts.User',null=True,blank=True,related_name='+')
class AdvanceRepayment(TenantModel):
 advance=relation(SalaryAdvance);payroll=relation(PayrollRecord);amount=money()
 class Meta: constraints=[models.UniqueConstraint(fields=['advance','payroll'],name='hr_advance_repayment')]
class EmployeeDocument(TenantModel):
 employee=relation(Employee);documentType=models.CharField(max_length=60);name=models.CharField(max_length=160)
 file=models.FileField(upload_to='private_hr/%Y/%m/')
 issueDate=models.DateField(null=True,blank=True)
 expiryDate=models.DateField(null=True,blank=True)
 uploadedBy=relation('accounts.User',null=True,blank=True,related_name='+')

class HRActivity(TenantModel):
 details=models.JSONField(default=dict)
 employee=relation(Employee)
 resource=models.CharField(max_length=40)
 action=models.CharField(max_length=40)
 recordId=models.CharField(max_length=40)
 actor=relation('accounts.User',null=True,blank=True,related_name='+')
