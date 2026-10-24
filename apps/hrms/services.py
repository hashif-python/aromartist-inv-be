from datetime import date,datetime,timedelta
from decimal import Decimal
import calendar,io
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError,PermissionDenied
from apps.erp import models as erp,services as es
from . import models as m
ZERO=Decimal('0')
def days(start,end):
 while start<=end:
  yield start
  start+=timedelta(days=1)
def shift_for(employee,day):
 a=m.ShiftAssignment.objects.filter(employee=employee,effectiveDate__lte=day).select_related('shift').order_by('-effectiveDate').first()
 return a.shift if a else None
def off_day(employee,day):
 if m.Holiday.objects.filter(organization=employee.organization,date=day).filter(erp.models.Q(branch=None)|erp.models.Q(branch=employee.branch)).exists():return 'Holiday'
 shift=shift_for(employee,day)
 if shift and day.weekday() in shift.weeklyOff:return 'Weekly Off'
 return None
def working_days(employee,start,end):return [d for d in days(start,end) if not off_day(employee,d)]
def employment(employee,day):
 if day<employee.joiningDate or (employee.leavingDate and day>employee.leavingDate):raise ValidationError('Date is outside this employee employment period.')
def unlocked(employee,start,end):
 for period in m.PayrollPeriod.objects.filter(organization=employee.organization,closed=True):
  first=date(period.year,period.month,1);last=date(period.year,period.month,calendar.monthrange(period.year,period.month)[1])
  if first<=end and last>=start:raise ValidationError('This payroll period is closed.')
 if m.PayrollRecord.objects.filter(employee=employee,status__in=['Approved','Paid'],period__year__gte=start.year,period__year__lte=end.year).exists():
  for p in m.PayrollRecord.objects.filter(employee=employee,status__in=['Approved','Paid']).select_related('period'):
   a=date(p.period.year,p.period.month,1);b=date(a.year,a.month,calendar.monthrange(a.year,a.month)[1])
   if a<=end and b>=start:raise ValidationError('This period has locked payroll. Corrections require an authorized future adjustment.')
def attendance_metrics(obj):
 employment(obj.employee,obj.date)
 obj.workingMinutes=obj.lateMinutes=obj.earlyMinutes=obj.overtimeMinutes=0
 off=off_day(obj.employee,obj.date)
 leave=m.LeaveRequest.objects.filter(employee=obj.employee,status='Approved',startDate__lte=obj.date,endDate__gte=obj.date).exists()
 if off and not obj.checkIn:obj.status=off
 elif leave:obj.status='Leave'
 if obj.checkOut and not obj.checkIn:raise ValidationError('Check in before checking out.')
 if obj.checkIn:
  if timezone.localdate(obj.checkIn)!=obj.date:raise ValidationError('Check-in must be on the attendance date.')
  end=obj.checkOut
  if end and (end<obj.checkIn or end-obj.checkIn>timedelta(hours=48)):raise ValidationError('Check-out must follow check-in within 48 hours.')
  shift=shift_for(obj.employee,obj.date)
  if shift:
   zone=timezone.get_current_timezone();start=timezone.make_aware(datetime.combine(obj.date,shift.start),zone);scheduled=timezone.make_aware(datetime.combine(obj.date+(timedelta(days=1) if shift.end<=shift.start else timedelta()),shift.end),zone)
   obj.lateMinutes=max(0,int((obj.checkIn-start).total_seconds()/60)-shift.graceMinutes)
   if end:
    obj.earlyMinutes=max(0,int((scheduled-end).total_seconds()/60))
    obj.overtimeMinutes=max(0,int((end-scheduled).total_seconds()/60)) if shift.overtimeEnabled else 0
  if end:obj.workingMinutes=max(0,int((end-obj.checkIn).total_seconds()/60)-(shift.breakMinutes if shift else 0))
 return obj
@transaction.atomic
def leave_action(user,obj,action):
 m.Employee.objects.select_for_update().get(pk=obj.employee_id)
 obj=m.LeaveRequest.objects.select_for_update().get(pk=obj.pk)
 unlocked(obj.employee,obj.startDate,obj.endDate)
 if action=='approve':
  if obj.employee.user_id==user.pk:raise PermissionDenied('You cannot approve your own leave.')
  if obj.status=='Approved':return obj
  if obj.status!='Pending':raise ValidationError('Only pending leave can be approved.')
  if m.LeaveRequest.objects.filter(employee=obj.employee,status='Approved',startDate__lte=obj.endDate,endDate__gte=obj.startDate).exclude(pk=obj.pk).exists():raise ValidationError('Leave overlaps an approved request.')
  balance,_=m.LeaveBalance.objects.get_or_create(organization=obj.organization,employee=obj.employee,leaveType=obj.leaveType,year=obj.startDate.year,defaults={'entitlement':obj.leaveType.annualDays})
  balance=m.LeaveBalance.objects.select_for_update().get(pk=balance.pk)
  if obj.leaveType.paid and balance.used+obj.days>balance.entitlement:raise ValidationError('Insufficient leave balance.')
  balance.used+=obj.days;balance.save()
  obj.status='Approved';obj.approvedBy=user
  for d in working_days(obj.employee,obj.startDate,obj.endDate):
   m.Attendance.objects.update_or_create(organization=obj.organization,employee=obj.employee,date=d,defaults={'status':'Leave','approved':True,'recordedBy':user})
 elif action=='reject':
  if obj.status!='Pending':raise ValidationError('Only pending leave can be rejected.')
  obj.status='Rejected';obj.approvedBy=user
 elif action=='cancel':
  if obj.status not in ['Pending','Approved']:raise ValidationError('Only pending or approved leave can be cancelled.')
  if obj.status=='Approved':
   balance=m.LeaveBalance.objects.select_for_update().get(employee=obj.employee,leaveType=obj.leaveType,year=obj.startDate.year);balance.used=max(ZERO,balance.used-obj.days);balance.save()
   m.Attendance.objects.filter(employee=obj.employee,date__gte=obj.startDate,date__lte=obj.endDate,status='Leave').update(status='Absent',approved=False)
  obj.status='Cancelled'
 obj.save();return obj
@transaction.atomic
def revision_approve(user,obj):
 m.Employee.objects.select_for_update().get(pk=obj.employee_id)
 obj=m.SalaryRevision.objects.select_for_update().get(pk=obj.pk)
 if obj.employee.user_id==user.pk:raise PermissionDenied('You cannot approve your own salary revision.')
 if obj.status=='Approved':return obj
 if obj.status!='Pending':raise ValidationError('Only pending revisions can be approved.')
 unlocked(obj.employee,obj.effectiveDate,date.today())
 old=m.SalaryStructure.objects.filter(employee=obj.employee,effectiveDate__lt=obj.effectiveDate).order_by('-effectiveDate').first()
 obj.previousSalary=old.basic if old else ZERO
 m.SalaryStructure.objects.create(organization=obj.organization,employee=obj.employee,effectiveDate=obj.effectiveDate,basic=obj.revisedSalary,allowances=obj.allowances,deductions=obj.deductions,overtimeHourly=obj.overtimeHourly,reason=obj.reason,approvedBy=user)
 obj.status='Approved';obj.approvedBy=user;obj.save();return obj
@transaction.atomic
def calculate(user,pay):
 m.Employee.objects.select_for_update().get(pk=pay.employee_id)
 pay=m.PayrollRecord.objects.select_for_update().select_related('employee','period').get(pk=pay.pk)
 period=m.PayrollPeriod.objects.select_for_update().get(pk=pay.period_id)
 if period.closed:raise ValidationError('This payroll period is closed.')
 e=m.Employee.objects.get(pk=pay.employee_id)
 if pay.status not in ['Draft','Calculated']:raise ValidationError('Approved or paid payroll is locked.')
 start=date(pay.period.year,pay.period.month,1);end=date(start.year,start.month,calendar.monthrange(start.year,start.month)[1]);denom=Decimal(end.day)
 if end>=timezone.localdate():raise ValidationError('Calculate only completed months.')
 start=max(start,e.joiningDate);end=min(end,e.leavingDate or end)
 if start>end:raise ValidationError('No employment days in this period.')
 salaries=list(m.SalaryStructure.objects.filter(employee=e,effectiveDate__lte=end).order_by('effectiveDate'))
 attendance={a.date:a for a in m.Attendance.objects.filter(employee=e,date__gte=start,date__lte=end)}
 leaves=list(m.LeaveRequest.objects.filter(employee=e,status='Approved',startDate__lte=end,endDate__gte=start).select_related('leaveType'))
 earned=ZERO;gross=ZERO;fixed=ZERO;unpaid=ZERO;ot=ZERO;snapshot=[]
 for day in days(start,end):
  salary=next((s for s in reversed(salaries) if s.effectiveDate<=day),None)
  if not salary:raise ValidationError(f'No salary structure effective on {day}.')
  leave=next((l for l in leaves if l.startDate<=day<=l.endDate),None)
  att=attendance.get(day);off=off_day(e,day)
  if not off and not leave and (not att or not att.approved):raise ValidationError(f'Approve attendance for {day} before calculating payroll.')
  fraction=Decimal(1) if off else ZERO if leave and not leave.leaveType.paid else Decimal('.5') if att and att.status=='Half Day' else ZERO if att and att.status in ['Absent','Leave'] and not leave and not off else Decimal(1)
  rate=(salary.basic+salary.allowances-salary.deductions)/denom
  if rate<0:raise ValidationError('Salary deductions exceed salary.')
  overtime=Decimal(att.overtimeMinutes)/60*salary.overtimeHourly if att and att.approved else ZERO
  earned+=rate*fraction+overtime;gross+=(salary.basic+salary.allowances)/denom*fraction+overtime;fixed+=salary.deductions/denom*fraction;unpaid+=rate*(1-fraction);ot+=overtime
  snapshot.append({'date':str(day),'salaryId':salary.pk,'basic':str(salary.basic),'allowances':str(salary.allowances),'deductions':str(salary.deductions),'paidFraction':str(fraction),'overtime':str(overtime),'status':off or ('Leave' if leave else att.status)})
 earned=es.cash(earned);allocations=[];deduct=ZERO
 for adv in m.SalaryAdvance.objects.filter(employee=e,status='Disbursed',deductionFrom__lte=end).order_by('date','pk'):
  amount=min(adv.amount-adv.repaid,adv.installment,max(ZERO,earned-deduct))
  if amount>0:allocations.append({'advanceId':adv.pk,'amount':str(amount)});deduct+=amount
 pay.earned=earned;pay.advanceDeduction=es.cash(deduct);pay.net=earned-pay.advanceDeduction;pay.status='Calculated'
 pay.snapshot={'employeeName':e.name,'employeeCode':e.employeeCode,'branchName':e.branch.name,'joiningDate':str(e.joiningDate),'proration':'calendar days; approved attendance; paid holidays and weekly off','days':snapshot,'grossSalary':str(es.cash(gross)),'fixedDeductions':str(es.cash(fixed)),'unpaidDeduction':str(es.cash(unpaid)),'overtime':str(es.cash(ot)),'advances':allocations}
 pay.save();pay.payrollcomponent_set.all().delete()
 for name,amount in [('Earned salary',pay.earned),('Advance recovery',pay.advanceDeduction),('Net payable',pay.net)]:m.PayrollComponent.objects.create(organization=pay.organization,payroll=pay,name=name,amount=amount)
 return pay
@transaction.atomic
def payroll_action(user,pay,action,method='Bank'):
 m.Employee.objects.select_for_update().get(pk=pay.employee_id)
 pay=m.PayrollRecord.objects.select_for_update().select_related('employee','period').get(pk=pay.pk)
 if action=='approve':
  if pay.employee.user_id==user.pk:raise PermissionDenied('You cannot approve your own payroll.')
  if pay.status in ['Approved','Paid']:return pay
  if pay.status!='Calculated':raise ValidationError('Calculate and review payroll first.')
  # Recalculate under lock so stale attendance/revisions/advance balances cannot post.
  pay=calculate(user,pay)
  for allocation in pay.snapshot['advances']:
   adv=m.SalaryAdvance.objects.select_for_update().get(pk=allocation['advanceId']);amount=Decimal(allocation['amount'])
   if amount>adv.amount-adv.repaid:raise ValidationError('Advance recovery exceeds remaining balance.')
   m.AdvanceRepayment.objects.create(organization=pay.organization,advance=adv,payroll=pay,amount=amount);adv.repaid+=amount;adv.save()
  pay.expense=erp.Expense.objects.create(organization=pay.organization,date=date(pay.period.year,pay.period.month,calendar.monthrange(pay.period.year,pay.period.month)[1]),category='Payroll',description=f'Salary {pay.employee.employeeCode}: {pay.period.year}-{pay.period.month:02}',amount=pay.earned,paymentMethod='Accrual',location=pay.employee.branch.name,reference=f'PAYROLL-{pay.pk}',status='Accrued',createdBy=user)
  pay.status='Approved';pay.approvedBy=user
 elif action=='pay':
  if pay.status=='Paid':return pay
  if pay.status!='Approved':raise ValidationError('Approve payroll before payment.')
  if method not in ['Cash','Bank','Bank Transfer']:raise ValidationError('Select Cash, Bank or Bank Transfer.')
  es.ledger(user,pay.net,method,'Outflow',f'PAYROLL-{pay.pk}','Salary payment','payroll',pay.pk)
  pay.status='Paid';pay.paidBy=user;pay.paidDate=timezone.localdate();pay.paymentMethod=method
  pay.expense.status='Paid';pay.expense.save(update_fields=['status'])
 pay.save();return pay
@transaction.atomic
def advance_action(user,adv,action,method='Bank'):
 m.Employee.objects.select_for_update().get(pk=adv.employee_id)
 adv=m.SalaryAdvance.objects.select_for_update().get(pk=adv.pk)
 if action=='approve':
  if adv.employee.user_id==user.pk:raise PermissionDenied('You cannot approve your own advance.')
  if adv.status!='Pending':raise ValidationError('Only pending advances can be approved.')
  adv.status='Approved';adv.approvedBy=user
 elif action=='reject':
  if adv.status!='Pending':raise ValidationError('Only pending advances can be rejected.')
  adv.status='Rejected';adv.approvedBy=user
 elif action=='disburse':
  if adv.status=='Disbursed':return adv
  if adv.status!='Approved':raise ValidationError('Approve the advance first.')
  if method not in ['Cash','Bank','Bank Transfer']:raise ValidationError('Select a valid payment method.')
  es.ledger(user,adv.amount,method,'Outflow',f'ADVANCE-{adv.pk}','Employee salary advance (receivable)','salary_advance',adv.pk)
  adv.status='Disbursed'
 adv.save();return adv

def document_pdf(title,lines):
 from reportlab.pdfgen import canvas
 from reportlab.lib.pagesizes import A4
 stream=io.BytesIO();c=canvas.Canvas(stream,pagesize=A4);c.setTitle(title);c.setFont('Helvetica-Bold',18);c.drawString(45,795,title)
 c.setFont('Helvetica',11);y=760
 for line in lines:
  if y<60:c.showPage();c.setFont('Helvetica',11);y=790
  text=str(line)
  for start in range(0,len(text),88):c.drawString(45,y,text[start:start+88]);y-=20
 c.save();stream.seek(0);return stream
