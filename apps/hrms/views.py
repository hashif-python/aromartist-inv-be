from datetime import date,timedelta
from decimal import Decimal
from django.db import transaction
from django.db.models import Sum,Q
from django.http import FileResponse,HttpResponse
from django.utils import timezone
from rest_framework import viewsets,serializers
from rest_framework.decorators import action
from rest_framework.permissions import BasePermission
from rest_framework.pagination import PageNumberPagination
from rest_framework.exceptions import ValidationError,PermissionDenied
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema,OpenApiTypes
from apps.accounts.permissions import has
from apps.accounts.access import employee_ids,scope,location_ids
from apps.erp.views import TenantViewSet
from . import models as m,services as svc
from .serializers import MODELS,serializer_for
NAMES={'employees':'employee','departments':'department','designations':'designation','attendance':'attendance','leave-types':'leave_type','leave-balances':'leave_balance','leaves':'leave','salary-structures':'salary','salary-revisions':'salary_revision','payroll-periods':'payroll_period','payroll':'payroll','salary-advances':'advance','documents':'document','shifts':'shift','shift-assignments':'shift_assignment','holidays':'holiday','policy':'policy'}
class HRPermission(BasePermission):
 def has_permission(self,request,view):
  if not request.user.is_authenticated or not request.user.organization_id:return False
  act=getattr(view,'action','list');act={'list':'view','retrieve':'view','partial_update':'edit','update':'edit','destroy':'delete','payslip':'download','certificate':'download','link_login':'link_login','activity':'view','close':'edit'}.get(act,act)
  from apps.accounts.scope_context import permission_context
  permission_context.set(f'hrms.{view.resource}.{act}')
  if act in ['check_in','check_out']:
   own=request.data.get('employee')
   if has(request.user,'hrms.self_attendance') and m.Employee.objects.filter(user=request.user,pk=own).exists():
    permission_context.set('hrms.self_attendance');return True
  return has(request.user,f'hrms.{view.resource}.{act}')
class Pagination(PageNumberPagination):
 page_size=25;page_size_query_param='page_size';max_page_size=200
class HRViewSet(TenantViewSet):
 permission_classes=[HRPermission];pagination_class=Pagination
 def get_queryset(self):
  if getattr(self,'swagger_fake_view',False):return self.queryset.none()
  qs=self.queryset.filter(organization_id=self.request.user.organization_id).order_by('-created_at')
  fields={f.name for f in qs.model._meta.fields}
  ids=employee_ids(self.request.user)
  if qs.model==m.Employee:qs=qs.filter(pk__in=ids)
  elif 'employee' in fields:qs=qs.filter(employee_id__in=ids)
  elif 'branch' in fields and scope(self.request.user)!='organization':qs=qs.filter(Q(branch=None)|Q(branch_id__in=location_ids(self.request.user)))
  for key in ['employee','branch','status','department','designation','year','month','date','period','leaveType','documentType']:
   if key in fields and self.request.query_params.get(key):
    value=self.request.query_params[key];field=qs.model._meta.get_field(key)
    if isinstance(field,m.models.DateField):value=serializers.DateField().run_validation(value)
    elif isinstance(field,m.models.IntegerField):value=serializers.IntegerField().run_validation(value)
    qs=qs.filter(**{key:value})
  for key,lookup in [('fromDate','date__gte'),('toDate','date__lte')]:
   if self.request.query_params.get(key):
    if qs.model==m.LeaveRequest:lookup='endDate__gte' if key=='fromDate' else 'startDate__lte'
    elif 'date' not in fields:continue
    qs=qs.filter(**{lookup:serializers.DateField().run_validation(self.request.query_params[key])})
  search=self.request.query_params.get('search')
  if search:
   q=Q();names=[f.name for f in qs.model._meta.fields if isinstance(f,(m.models.CharField,m.models.TextField))]
   for name in names:q|=Q(**{name+'__icontains':search})
   if 'employee' in fields:q|=Q(employee__name__icontains=search)
   qs=qs.filter(q)
  return qs
 def finalize_response(self,request,response,*args,**kwargs):
  response=super().finalize_response(request,response,*args,**kwargs)
  if request.method in ['POST','PATCH','PUT'] and 200<=response.status_code<300 and hasattr(request.user,'organization_id'):
   record_id=self.kwargs.get('pk') or (response.data.get('id') if isinstance(getattr(response,'data',None),dict) else None)
   obj=self.queryset.filter(pk=record_id,organization=request.user.organization).first() if record_id else None
   employee=obj if isinstance(obj,m.Employee) else getattr(obj,'employee',None)
   if employee:m.HRActivity.objects.create(organization=request.user.organization,employee=employee,resource=self.resource,action=self.action,recordId=str(record_id),actor=request.user,details={'before':getattr(self,'audit_before',{}),'after':{'entitlement':str(obj.entitlement),'used':str(obj.used),'year':obj.year,'leaveType':str(obj.leaveType_id)}} if isinstance(obj,m.LeaveBalance) else {})
  return response
 def list(self,request,*args,**kwargs):
  qs=self.get_queryset();page=self.paginate_queryset(qs)
  return self.get_paginated_response(self.get_serializer(page,many=True).data)
 def history_lock(self,serializer):
  data=serializer.validated_data;obj=serializer.instance
  employee=data.get('employee') or getattr(obj,'employee',None)
  if employee:
   m.Employee.objects.select_for_update().get(pk=employee.pk)
   model=serializer.Meta.model
   def v(key):return data.get(key,getattr(obj,key,None))
   if model==m.Attendance:svc.unlocked(employee,v('date'),v('date'))
   elif model==m.LeaveRequest:svc.unlocked(employee,v('startDate'),v('endDate'))
   elif model in [m.SalaryStructure,m.SalaryRevision,m.ShiftAssignment]:svc.unlocked(employee,v('effectiveDate'),date.max)
 def perform_create(self,serializer):
  initial_shift=serializer.validated_data.pop('initialShift',None);initial_salary=serializer.validated_data.pop('initialSalary',None)
  self.history_lock(serializer)
  if serializer.Meta.model==m.PayrollRecord:
   period=m.PayrollPeriod.objects.select_for_update().get(pk=serializer.validated_data['period'].pk)
   if period.closed:raise ValidationError('This payroll period is closed.')
  extra={}
  if serializer.Meta.model==m.Attendance:extra['recordedBy']=self.request.user
  if serializer.Meta.model==m.EmployeeDocument:extra['uploadedBy']=self.request.user
  if serializer.Meta.model==m.SalaryStructure:extra['approvedBy']=self.request.user
  employee=serializer.save(organization=self.request.user.organization,**extra)
  if isinstance(employee,m.Employee):
   from apps.accounts.scope_context import permission_context
   for resource,model,data in [('shift_assignment',m.ShiftAssignment,{'employee':employee.pk,'shift':initial_shift,'effectiveDate':employee.joiningDate} if initial_shift else None),('salary',m.SalaryStructure,{**initial_salary,'employee':employee.pk} if isinstance(initial_salary,dict) and initial_salary else None)]:
    if not data:continue
    if not has(self.request.user,f'hrms.{resource}.create'):raise PermissionDenied('Initial shift/salary creation needs its own permission.')
    token=permission_context.set(f'hrms.{resource}.create')
    try:
     child=serializer_for(model)(data=data,context={'request':self.request});child.is_valid(raise_exception=True);child.save(organization=employee.organization,**({'approvedBy':self.request.user} if model==m.SalaryStructure else {}))
    finally:permission_context.reset(token)
 def perform_update(self,serializer):
  if serializer.validated_data.pop('initialShift',None) or serializer.validated_data.pop('initialSalary',None):raise ValidationError('Use dated shift assignments or salary history for existing employees.')
  self.history_lock(serializer)
  instance=serializer.instance
  if isinstance(instance,m.LeaveBalance):self.audit_before={'entitlement':str(instance.entitlement),'used':str(instance.used),'year':instance.year,'leaveType':str(instance.leaveType_id)}
  if isinstance(instance,m.EmployeeDocument):
   old=instance.file
   serializer.save(uploadedBy=self.request.user)
   if 'file' in serializer.validated_data:transaction.on_commit(lambda:old.storage.delete(old.name))
  else:
   saved=serializer.save()
   if isinstance(saved,m.Employee) and saved.user_id:
    from apps.accounts.models import User
    User.objects.filter(pk=saved.user_id,organization=saved.organization).update(first_name=saved.name,email=saved.email,phone=saved.phone)
 def perform_destroy(self,obj):
  if isinstance(obj,m.PayrollPeriod) and obj.closed:raise ValidationError('Closed periods cannot be deleted.')
  if isinstance(obj,(m.PayrollRecord,m.SalaryStructure,m.SalaryRevision,m.SalaryAdvance,m.Attendance,m.LeaveRequest)):
   raise ValidationError('History is protected; use a status action instead.')
  if isinstance(obj,m.ShiftAssignment):svc.unlocked(obj.employee,obj.effectiveDate,date.max)
  if isinstance(obj,m.Holiday):
   employees=m.Employee.objects.filter(organization=obj.organization)
   if obj.branch_id:employees=employees.filter(branch=obj.branch)
   for emp in employees:svc.unlocked(emp,obj.date,obj.date)
  employee=getattr(obj,'employee',None)
  if employee:m.HRActivity.objects.create(organization=obj.organization,employee=employee,resource=self.resource,action='delete',recordId=str(obj.pk),actor=self.request.user)
  if isinstance(obj,m.EmployeeDocument):
   old=obj.file;obj.delete();transaction.on_commit(lambda:old.storage.delete(old.name))
  else:obj.delete()
 @action(detail=False,methods=['get'])
 @extend_schema(responses={(200,"text/csv"):OpenApiTypes.BINARY})
 def export(self,request):
  import csv,io
  rows=self.get_serializer(self.get_queryset(),many=True).data
  fields=[f.name for f in self.queryset.model._meta.fields if f.name not in ['organization','file']]
  stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore');writer.writeheader()
  def safe(v):
   text=str(v if v is not None else '')
   return "'"+text if text.startswith(('=','+','-','@')) else text
  for row in rows:writer.writerow({k:safe(row.get(k,'')) for k in fields})
  response=HttpResponse(stream.getvalue(),content_type='text/csv');response['Content-Disposition']=f'attachment; filename="{self.resource}.csv"';return response
class EmployeeViewSet(HRViewSet):
 queryset=m.Employee.objects.all();serializer_class=serializer_for(m.Employee);resource='employee'
 @action(detail=True,methods=['get'])
 def activity(self,request,pk=None):
  employee=self.get_object()
  rows=m.HRActivity.objects.filter(employee=employee).order_by('-created_at')
  from apps.accounts.scope_context import permission_context
  resources=[]
  for name in set(NAMES.values()):
   if not has(request.user,f'hrms.{name}.view'):continue
   token=permission_context.set(f'hrms.{name}.view')
   try:
    if employee.pk in employee_ids(request.user):resources.append(name)
   finally:permission_context.reset(token)
  rows=rows.filter(resource__in=resources)
  page=self.paginate_queryset(rows)
  return self.get_paginated_response([dict(id=x.pk,date=x.created_at,resource=x.resource,action=x.action,actor=x.actor.username if x.actor else '',recordId=x.recordId,details=x.details) for x in page])
 @action(detail=True,methods=['post'])
 @transaction.atomic
 def link_login(self,request,pk=None):
  from apps.accounts.access_views import provision_user
  if not has(request.user,'access.users.manage'):raise PermissionDenied('User administration permission required.')
  employee=self.get_object();existing=None
  if request.data.get('userId'):
   from django.contrib.auth import get_user_model
   from django.shortcuts import get_object_or_404
   existing=get_object_or_404(get_user_model(),pk=request.data['userId'],organization=request.user.organization)
   if m.Employee.objects.filter(user=existing).exclude(pk=employee.pk).exists():raise ValidationError('Login is already linked to another employee.')
   if employee.user_id and employee.user_id!=existing.pk:raise ValidationError('Employee already has a linked login.')
  user=provision_user(request,request.data,employee=employee,existing=existing);employee.user=user;employee.save();return Response({'userId':user.pk,'username':user.username})
class AttendanceViewSet(HRViewSet):
 queryset=m.Attendance.objects.all();serializer_class=serializer_for(m.Attendance);resource='attendance'
 @action(detail=True,methods=['post'])
 @transaction.atomic
 def approve(self,request,pk=None):
  obj=self.get_object();m.Employee.objects.select_for_update().get(pk=obj.employee_id);svc.unlocked(obj.employee,obj.date,obj.date)
  if obj.employee.user_id==request.user.pk:raise PermissionDenied('Self approval is not allowed.')
  obj.approved=True;obj.save();return Response(self.get_serializer(obj).data)
 def punch(self,request,out=False):
  policy=m.Policy.objects.filter(organization=request.user.organization).first()
  employee=m.Employee.objects.filter(pk=request.data.get('employee'),pk__in=employee_ids(request.user)).first()
  if not employee:raise PermissionDenied('Employee is outside your scope.')
  if employee.status!='active':raise ValidationError('Inactive employees cannot check in or out.')
  is_self=employee.user_id==request.user.pk
  if is_self and (not policy or not policy.selfAttendance):raise PermissionDenied('Company self-attendance is disabled.')
  m.Employee.objects.select_for_update().get(pk=employee.pk)
  if out:
   obj=m.Attendance.objects.filter(employee=employee,checkIn__isnull=False,checkOut=None).order_by('-date').first()
   if not obj:raise ValidationError('No open check-in.')
   svc.unlocked(employee,obj.date,obj.date);obj.checkOut=timezone.now()
  else:
   day=timezone.localdate();svc.unlocked(employee,day,day)
   obj,_=m.Attendance.objects.get_or_create(organization=employee.organization,employee=employee,date=day)
   if obj.checkIn:raise ValidationError('Already checked in.')
   obj.checkIn=timezone.now();obj.status='Present';obj.recordedBy=request.user
  obj.approved=False;svc.attendance_metrics(obj);obj.save();return Response(self.get_serializer(obj).data)
 @action(detail=False,methods=['post'])
 @transaction.atomic
 def check_in(self,request):return self.punch(request)
 @action(detail=False,methods=['post'])
 @transaction.atomic
 def check_out(self,request):return self.punch(request,True)
class LeaveViewSet(HRViewSet):
 queryset=m.LeaveRequest.objects.all();serializer_class=serializer_for(m.LeaveRequest);resource='leave'
 @action(detail=True,methods=['post'])
 def approve(self,request,pk=None):return Response(self.get_serializer(svc.leave_action(request.user,self.get_object(),'approve')).data)
 @action(detail=True,methods=['post'])
 def reject(self,request,pk=None):return Response(self.get_serializer(svc.leave_action(request.user,self.get_object(),'reject')).data)
 @action(detail=True,methods=['post'])
 def cancel(self,request,pk=None):return Response(self.get_serializer(svc.leave_action(request.user,self.get_object(),'cancel')).data)
class RevisionViewSet(HRViewSet):
 queryset=m.SalaryRevision.objects.all();serializer_class=serializer_for(m.SalaryRevision);resource='salary_revision'
 @action(detail=True,methods=['post'])
 def approve(self,request,pk=None):return Response(self.get_serializer(svc.revision_approve(request.user,self.get_object())).data)
class PayrollViewSet(HRViewSet):
 queryset=m.PayrollRecord.objects.all();serializer_class=serializer_for(m.PayrollRecord);resource='payroll'
 @action(detail=True,methods=['post'])
 def calculate(self,request,pk=None):return Response(self.get_serializer(svc.calculate(request.user,self.get_object())).data)
 @action(detail=True,methods=['post'])
 def approve(self,request,pk=None):return Response(self.get_serializer(svc.payroll_action(request.user,self.get_object(),'approve')).data)
 @action(detail=True,methods=['post'])
 def pay(self,request,pk=None):return Response(self.get_serializer(svc.payroll_action(request.user,self.get_object(),'pay',request.data.get('method','Bank'))).data)
 @action(detail=True,methods=['get'])
 @extend_schema(responses={(200,"application/pdf"):OpenApiTypes.BINARY})
 def payslip(self,request,pk=None):
  obj=self.get_object()
  if obj.status not in ['Approved','Paid']:raise ValidationError('Approve payroll before issuing payslip.')
  pdf=svc.document_pdf('PerfumASol Payslip',[obj.snapshot.get('employeeName',obj.employee.name),obj.snapshot.get('employeeCode',obj.employee.employeeCode),f'Branch: {obj.snapshot.get("branchName",obj.employee.branch.name)}',f'{obj.period.year}-{obj.period.month:02}',f'Gross salary: {obj.snapshot.get("grossSalary",obj.earned)}',f'Fixed deductions: {obj.snapshot.get("fixedDeductions",0)}',f'Unpaid salary deduction: {obj.snapshot.get("unpaidDeduction",0)}',f'Overtime: {obj.snapshot.get("overtime",0)}',f'Earned salary: {obj.earned}',f'Advance recovery: {obj.advanceDeduction}',f'Net payable: {obj.net}',f'Status: {obj.status}',f'Payment date: {obj.paidDate or "Not yet paid"}'])
  return FileResponse(pdf,as_attachment=True,filename='payslip.pdf')
class AdvanceViewSet(HRViewSet):
 queryset=m.SalaryAdvance.objects.all();serializer_class=serializer_for(m.SalaryAdvance);resource='advance'
 @action(detail=True,methods=['post'])
 def approve(self,request,pk=None):return Response(self.get_serializer(svc.advance_action(request.user,self.get_object(),'approve')).data)
 @action(detail=True,methods=['post'])
 def reject(self,request,pk=None):return Response(self.get_serializer(svc.advance_action(request.user,self.get_object(),'reject')).data)
 @action(detail=True,methods=['post'])
 def disburse(self,request,pk=None):return Response(self.get_serializer(svc.advance_action(request.user,self.get_object(),'disburse',request.data.get('method','Bank'))).data)
class DocumentViewSet(HRViewSet):
 queryset=m.EmployeeDocument.objects.all();serializer_class=serializer_for(m.EmployeeDocument);resource='document'
 @action(detail=True,methods=['get'])
 @extend_schema(responses={(200,"application/octet-stream"):OpenApiTypes.BINARY})
 def download(self,request,pk=None):
  obj=self.get_object();return FileResponse(obj.file.open('rb'),as_attachment=True,filename=obj.file.name.split('/')[-1])
 @action(detail=False,methods=['get'])
 @extend_schema(responses={(200,"application/pdf"):OpenApiTypes.BINARY})
 def certificate(self,request):
  e=m.Employee.objects.filter(pk=request.query_params.get('employee'),pk__in=employee_ids(request.user)).first()
  if not e:raise PermissionDenied('Employee is outside your scope.')
  kind=request.query_params.get('type','Employment Certificate')
  if kind not in ['Employment Certificate','Experience Certificate','Offer Letter','Salary Certificate']:raise ValidationError('Choose a supported certificate.')
  lines=[e.organization.name,f'Employee: {e.name} ({e.employeeCode})',f'Designation: {e.designation.name}',f'Branch: {e.branch.name}',f'Joined: {e.joiningDate}',f'Issued: {timezone.localdate()}']
  if kind=='Employment Certificate':lines.append(f'This is to certify that {e.name} is employed with {e.organization.name} as {e.designation.name} from {e.joiningDate}. Current employment status: {e.status}.')
  elif kind=='Experience Certificate':lines.append(f'This certifies the recorded service of {e.name} as {e.designation.name} from {e.joiningDate} to {e.leavingDate or timezone.localdate()}.')
  elif kind=='Offer Letter':lines.extend([f'Employment offer record for {e.name}: position {e.designation.name}, {e.employmentType}, at {e.branch.name}.',f'Recorded joining date: {e.joiningDate}. Please review this record alongside the approved employment contract.'])
  if kind=='Salary Certificate':
   if not has(request.user,'hrms.salary.view'):raise PermissionDenied('Salary access is required.')
   sal=m.SalaryStructure.objects.filter(employee=e,effectiveDate__lte=timezone.localdate()).order_by('-effectiveDate').first()
   if not sal:raise ValidationError('Configure salary first.')
   lines.extend([f'This certifies the recorded salary of {e.name} effective from {sal.effectiveDate}.',f'Monthly basic: {sal.basic}',f'Monthly allowances: {sal.allowances}',f'Monthly gross salary: {sal.basic+sal.allowances}',f'Monthly fixed deductions: {sal.deductions}'])
  lines.extend(['Authorized signature: ____________________','Company stamp: ____________________'])
  return FileResponse(svc.document_pdf(kind,lines),as_attachment=True,filename='certificate.pdf')
class DashboardSerializer(serializers.Serializer):
 totalEmployees=serializers.IntegerField();activeEmployees=serializers.IntegerField();presentToday=serializers.IntegerField();absentToday=serializers.IntegerField();onLeaveToday=serializers.IntegerField();pendingLeave=serializers.IntegerField();upcomingExpiry=serializers.IntegerField(allow_null=True);payrollStatus=serializers.ListField(child=serializers.DictField());attendanceTrend=serializers.ListField(child=serializers.DictField())
class DashboardViewSet(viewsets.ViewSet):
 serializer_class=DashboardSerializer
 permission_classes=[HRPermission];resource='dashboard'
 def list(self,request):
  employees=m.Employee.objects.filter(pk__in=employee_ids(request.user),organization=request.user.organization);today=timezone.localdate();attendance=m.Attendance.objects.filter(employee__in=employees,date=today,approved=True)
  data={'totalEmployees':employees.count(),'activeEmployees':employees.filter(status='active').count(),'presentToday':attendance.filter(status='Present').count(),'absentToday':attendance.filter(status='Absent').count(),'onLeaveToday':m.LeaveRequest.objects.filter(employee__in=employees,status='Approved',startDate__lte=today,endDate__gte=today).count(),'pendingLeave':m.LeaveRequest.objects.filter(employee__in=employees,status='Pending').count(),'upcomingExpiry':m.EmployeeDocument.objects.filter(employee__in=employees,expiryDate__gte=today,expiryDate__lte=today+timedelta(days=30)).count() if has(request.user,'hrms.document.view') else None,'payrollStatus':[],'attendanceTrend':[]}
  if has(request.user,'hrms.payroll.view'):
   data['payrollStatus']=list(m.PayrollRecord.objects.filter(employee__in=employees,period__year=today.year,period__month=today.month).values('status').annotate(count=m.models.Count('pk')))
  for day in svc.days(today-timedelta(days=6),today):data['attendanceTrend'].append({'date':str(day),'present':m.Attendance.objects.filter(employee__in=employees,date=day,status='Present',approved=True).count()})
  return Response(data)

class PeriodViewSet(HRViewSet):
 queryset=m.PayrollPeriod.objects.all();serializer_class=serializer_for(m.PayrollPeriod);resource='payroll_period'
 @action(detail=True,methods=['post'])
 @transaction.atomic
 def close(self,request,pk=None):
  if scope(request.user)!='organization':raise PermissionDenied('Organization scope is required to close a payroll period.')
  period=m.PayrollPeriod.objects.select_for_update().get(pk=self.get_object().pk)
  if date(period.year,period.month,1)>=timezone.localdate().replace(day=1):raise ValidationError('Only completed months can be closed.')
  records=m.PayrollRecord.objects.filter(period=period)
  if not records.exists() or records.exclude(status='Paid').exists():raise ValidationError('Complete payment for all payroll records before closing this period.')
  period.closed=True;period.save(update_fields=['closed'])
  return Response(self.get_serializer(period).data)
