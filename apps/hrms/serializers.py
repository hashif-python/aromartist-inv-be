from datetime import date
from decimal import Decimal
from rest_framework import serializers
from apps.erp.serializers import TenantSerializer
from apps.accounts.access import employee_ids,scope
from . import models as m,services as svc
class HRSerializer(TenantSerializer):
 employeeName=serializers.SerializerMethodField()
 def get_employeeName(self,obj) -> str:return getattr(getattr(obj,'employee',None),'name','')
 def get_fields(self):
  fields=super().get_fields();request=self.context.get('request');user=getattr(request,'user',None)
  if not user or not getattr(user,'organization_id',None):return fields
  for field in fields.values():
   if isinstance(field,serializers.PrimaryKeyRelatedField) and field.queryset is not None and field.queryset.model==m.Employee:field.queryset=field.queryset.filter(pk__in=employee_ids(user))
  if self.Meta.model==m.Employee:
   fields['initialShift']=serializers.CharField(write_only=True,required=False,allow_null=True,allow_blank=True)
   fields['initialSalary']=serializers.JSONField(write_only=True,required=False)
  if self.Meta.model==m.Employee and 'department' in fields:fields['department'].read_only=True;fields['department'].required=False
  return fields
 def validate(self,attrs):
  attrs=super().validate(attrs);model=self.Meta.model;user=self.context['request'].user
  def value(key):
   if key in attrs:return attrs[key]
   if self.instance:return getattr(self.instance,key,None)
   try:return model._meta.get_field(key).get_default()
   except Exception:return None
  employee=value('employee')
  if employee and scope(user)=='own' and employee.user_id!=user.pk:raise serializers.ValidationError('Choose your own employee record.')
  if self.instance and hasattr(self.instance,'employee') and 'employee' in attrs and attrs['employee']!=self.instance.employee:raise serializers.ValidationError('Employee cannot be changed on historical records.')
  if model==m.EmployeeDocument and value('issueDate') and value('expiryDate') and value('expiryDate')<value('issueDate'):raise serializers.ValidationError('Expiry date must not precede issue date.')
  if model==m.Employee:
   if 'initialSalary' in attrs and not isinstance(attrs['initialSalary'],dict):raise serializers.ValidationError('Initial salary must be an object.')
   branch=value('branch');manager=value('manager');department=value('department');designation=value('designation')
   from apps.accounts.access import location_ids
   if branch.kind!='Branch' or branch.status!='active':raise serializers.ValidationError({'branch':'Choose an active branch.'})
   if scope(user)!='organization' and branch.pk not in location_ids(user):raise serializers.ValidationError({'branch':'Branch is outside your scope.'})
   # Historical departments are preserved but no longer constrain employee creation.
   if self.instance:attrs.pop('department',None)
   else:attrs['department']=None
   if value('dateOfBirth') and value('dateOfBirth')>=value('joiningDate'):raise serializers.ValidationError('Birth date must precede joining date.')
   if value('leavingDate') and value('leavingDate')<value('joiningDate'):raise serializers.ValidationError('Leaving date precedes joining date.')
   if self.instance and m.PayrollRecord.objects.filter(employee=self.instance,status__in=['Approved','Paid']).exists() and any(key in attrs and attrs[key]!=getattr(self.instance,key) for key in ['joiningDate','leavingDate']):raise serializers.ValidationError('Employment dates are protected by posted payroll. Use an authorized correction process.')
   if manager and self.instance:
    seen={self.instance.pk}
    while manager:
     if manager.pk in seen:raise serializers.ValidationError('Reporting manager hierarchy cannot contain a cycle.')
     seen.add(manager.pk);manager=manager.manager
  if model==m.Shift:
   if not isinstance(value('weeklyOff'),list) or any(type(i)!=int or not 0<=i<=6 for i in value('weeklyOff')):raise serializers.ValidationError('Weekly off must be weekday numbers 0 (Monday) to 6 (Sunday).')
   if self.instance and m.PayrollRecord.objects.filter(employee__shiftassignment__shift=self.instance,status__in=['Approved','Paid']).exists():raise serializers.ValidationError('This shift is used by locked payroll. Create a new shift and a dated assignment.')
   duration=(value('end').hour*60+value('end').minute-value('start').hour*60-value('start').minute)%1440 or 1440
   if value('breakMinutes')>=duration or value('graceMinutes')>1440:raise serializers.ValidationError('Break must be shorter than the shift and grace must be at most one day.')
  if model==m.Holiday:
   from apps.accounts.access import location_ids
   branch=value('branch')
   if branch and branch.kind!='Branch':raise serializers.ValidationError('Choose a branch.')
   if self.instance:
    original=m.Employee.objects.filter(organization=user.organization)
    if self.instance.branch_id:original=original.filter(branch=self.instance.branch)
    for emp in original:svc.unlocked(emp,self.instance.date,self.instance.date)
   employees=m.Employee.objects.filter(organization=user.organization)
   if branch:employees=employees.filter(branch=branch)
   for emp in employees:svc.unlocked(emp,value('date'),value('date'))
   if scope(user)!='organization' and (not branch or branch.pk not in location_ids(user)):raise serializers.ValidationError('Choose an assigned branch for this holiday.')
  if model==m.ShiftAssignment:
   svc.employment(employee,value('effectiveDate'));svc.unlocked(employee,value('effectiveDate'),date.max)
   if self.instance:raise serializers.ValidationError('Create a dated shift assignment to retain history.')
  if model==m.Employee and self.instance and self.instance.user_id==user.pk:raise serializers.ValidationError('Ask HR to update your employment profile.')
  if model==m.LeaveType and value('annualDays')<0:raise serializers.ValidationError('Entitlement cannot be negative.')
  if model==m.LeaveBalance:
   if not 1900<=value('year')<=2200:raise serializers.ValidationError('Enter a valid balance year.')
   if value('entitlement')<0:raise serializers.ValidationError('Entitlement cannot be negative.')
   if self.instance and value('entitlement')<self.instance.used:raise serializers.ValidationError('Entitlement cannot be below leave already used.')
  if model==m.LeaveRequest:
   if self.instance and self.instance.status!='Pending':raise serializers.ValidationError('Reviewed leave is locked; use cancellation.')
   start=value('startDate');end=value('endDate')
   if end<start or end.year!=start.year:raise serializers.ValidationError('Dates must be ordered and in one calendar year. Split requests across years.')
   svc.employment(employee,start);svc.employment(employee,end);svc.unlocked(employee,start,end)
   if m.LeaveRequest.objects.filter(employee=employee,status__in=['Pending','Approved'],startDate__lte=end,endDate__gte=start).exclude(pk=getattr(self.instance,'pk',None)).exists():raise serializers.ValidationError('Leave request overlaps an existing request.')
   attrs['days']=Decimal(len(svc.working_days(employee,start,end)))
   if attrs['days']<=0:raise serializers.ValidationError('No working days in this request.')
  if model in [m.SalaryStructure,m.SalaryRevision]:
   effective=value('effectiveDate');svc.employment(employee,effective);svc.unlocked(employee,effective,date.max)
   if self.instance:raise serializers.ValidationError('Salary history is immutable; create a dated revision.')
   if model==m.SalaryStructure and value('deductions')>value('basic')+value('allowances'):raise serializers.ValidationError('Deductions exceed salary.')
  if model==m.SalaryAdvance:
   if self.instance and self.instance.status!='Pending':raise serializers.ValidationError('Reviewed advances are locked.')
   if value('amount')<=0 or value('installment')<=0 or value('installment')>value('amount'):raise serializers.ValidationError('Advance and installment must be positive; installment cannot exceed advance.')
   if value('deductionFrom')<value('date'):raise serializers.ValidationError('Deduction schedule cannot precede advance date.')
  if model==m.PayrollPeriod and not (1<=value('month')<=12 and 1900<=value('year')<=2200):raise serializers.ValidationError('Enter a valid payroll month and year.')
  if model==m.PayrollRecord and value('period').closed:raise serializers.ValidationError('This payroll period is closed.')
  if model==m.PayrollPeriod and self.instance and self.instance.closed:raise serializers.ValidationError('Closed periods cannot be edited.')
  if model==m.PayrollRecord and self.instance:raise serializers.ValidationError('Use calculate, approve or pay actions; payroll values are server controlled.')
  if model==m.Attendance:
   employee=value('employee');day=value('date');svc.unlocked(employee,day,day)
   obj=m.Attendance(employee=employee,date=day,status=value('status') or 'Present',checkIn=value('checkIn'),checkOut=value('checkOut'));svc.attendance_metrics(obj)
   for key in ['status','workingMinutes','lateMinutes','earlyMinutes','overtimeMinutes']:attrs[key]=getattr(obj,key)
   if 'approved' not in attrs:attrs['approved']=False
   if 'approved' in attrs:
    from apps.accounts.permissions import has
    if attrs['approved'] and employee.user_id==user.pk:raise serializers.ValidationError('Self approval is not allowed.')
    if attrs['approved'] and not has(user,'hrms.attendance.approve'):raise serializers.ValidationError('Attendance approval permission is required.')
  return attrs
 def validate_file(self,file):
  if file.size>10*1024*1024:raise serializers.ValidationError('Maximum upload size is 10 MB.')
  from pathlib import Path
  ext=Path(file.name).suffix.lower()
  if ext not in ['.pdf','.png','.jpg','.jpeg']:raise serializers.ValidationError('Use a PDF, PNG or JPEG file extension.')
  head=file.read(16);file.seek(0)
  if not (head.startswith(b'%PDF-') or head.startswith(b'\x89PNG\r\n\x1a\n') or head.startswith(b'\xff\xd8\xff')):raise serializers.ValidationError('Upload PDF, PNG or JPEG documents only.')
  return file
 def to_representation(self,instance):
  data=super().to_representation(instance)
  if isinstance(instance,m.EmployeeDocument):
   data['downloadUrl']=f'/api/v1/hrms/documents/{instance.pk}/download/'
   data['status']='Expired' if instance.expiryDate and instance.expiryDate<date.today() else 'Expiring Soon' if instance.expiryDate and (instance.expiryDate-date.today()).days<=30 else 'Valid'
  if isinstance(instance,m.Attendance):
   shift=svc.shift_for(instance.employee,instance.date)
   data.update(branchName=instance.employee.branch.name,shiftName=shift.name if shift else '',workHours=round(instance.workingMinutes/60,2))
  if isinstance(instance,m.Holiday):data['branchName']=instance.branch.name if instance.branch else 'All branches'
  if isinstance(instance,m.Employee):data.update(branchName=instance.branch.name,designationName=instance.designation.name,userName=instance.user.username if instance.user else '')
  if isinstance(instance,m.Employee) and instance.user:
   from apps.accounts.permissions import has
   from apps.accounts.scope_context import permission_context
   from apps.accounts.access import location_ids
   user=self.context['request'].user;token=permission_context.set('access.users.manage')
   try:allowed=has(user,'access.users.manage') and (scope(user)=='organization' or (instance.pk in employee_ids(user) and set(instance.user.branchAssignments.values_list('branch_id',flat=True)).issubset(location_ids(user))))
   finally:permission_context.reset(token)
   if instance.user_id==user.pk or allowed:data['account']={'id':instance.user_id,'username':instance.user.username,'active':instance.user.is_active,'roles':list(instance.user.roleAssignments.values_list('role__name',flat=True))}
  if isinstance(instance,m.LeaveBalance):data['remaining']=instance.entitlement-instance.used
  if isinstance(instance,m.SalaryAdvance):
   data['remaining']=instance.amount-instance.repaid
   from apps.accounts.permissions import has
   from apps.accounts.scope_context import permission_context
   user=self.context['request'].user;token=permission_context.set('hrms.payroll.view')
   try:allow=has(user,'hrms.payroll.view') and instance.employee_id in employee_ids(user)
   finally:permission_context.reset(token)
   if allow:data['deductionHistory']=[dict(period=f'{x.payroll.period.year}-{x.payroll.period.month:02}',amount=x.amount) for x in instance.advancerepayment_set.select_related('payroll__period').all()]
  if isinstance(instance,m.PayrollRecord):data.update(periodLabel=f'{instance.period.year}-{instance.period.month:02}',grossSalary=instance.snapshot.get('grossSalary',0),fixedDeductions=instance.snapshot.get('fixedDeductions',0))
  return data
READ_ONLY=['organization','created_at','updated_at','recordedBy','uploadedBy','approvedBy','paidBy','employeeName']
MODELS={'employees':m.Employee,'departments':m.Department,'designations':m.Designation,'attendance':m.Attendance,'leave-types':m.LeaveType,'leave-balances':m.LeaveBalance,'leaves':m.LeaveRequest,'salary-structures':m.SalaryStructure,'salary-revisions':m.SalaryRevision,'payroll-periods':m.PayrollPeriod,'payroll':m.PayrollRecord,'salary-advances':m.SalaryAdvance,'documents':m.EmployeeDocument,'shifts':m.Shift,'shift-assignments':m.ShiftAssignment,'holidays':m.Holiday,'policy':m.Policy}
EXTRA={m.PayrollPeriod:['closed'],m.Employee:['user'],m.EmployeeDocument:['file'],m.Attendance:['workingMinutes','lateMinutes','earlyMinutes','overtimeMinutes'],m.LeaveRequest:['days','status'],m.LeaveBalance:['used'],m.SalaryRevision:['previousSalary','status'],m.PayrollRecord:['status','earned','advanceDeduction','net','snapshot','expense','paidDate','paymentMethod'],m.SalaryAdvance:['repaid','status']}
def serializer_for(model):
 meta=type('Meta',(TenantSerializer.Meta,),{'model':model,'read_only_fields':READ_ONLY+EXTRA.get(model,[])})
 attrs={'Meta':meta}
 if model==m.EmployeeDocument:attrs['file']=serializers.FileField(write_only=True,required=True)
 return type(model.__name__+'Serializer',(HRSerializer,),attrs)
