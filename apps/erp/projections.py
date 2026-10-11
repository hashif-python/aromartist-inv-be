from datetime import timedelta
from django.db import transaction
from django.utils.timezone import localdate
from rest_framework import generics, serializers
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from apps.accounts.permissions import BusinessPermission, has
from apps.accounts.access import scoped_erp,employee_ids,effective_permissions
from . import services as svc, models as m, serializers as s, reports
from .views import InputSerializer

class Projection(generics.GenericAPIView):
    permission_classes=[BusinessPermission];serializer_class=InputSerializer
    read_permissions=['inventory.view'];write_permissions=['*'];action_permissions={}
    mode='stock'
    def get(self,request):
        u=request.user;mode=self.mode
        if mode=='stock': data=reports.stock_rows(u)
        elif mode=='low':
            data=[dict(r,shortage=max(0,r['minStock']-r['available'])) for r in reports.stock_rows(u) if r['stockStatus']!='Optimal']
        elif mode=='reports': data=reports.build_report(u,request.query_params)
        elif mode in ['dashboard','alerts']:
            today=localdate();month=today.replace(day=1)
            report=reports.build_report(u,{'fromDate':str(month),'toDate':str(today)})
            day=reports.build_report(u,{'fromDate':str(today),'toDate':str(today)})
            inventory=report['inventorySummary']
            pending=scoped_erp(m.Transfer.objects.filter(organization=u.organization),u).exclude(status__in=['Received','Cancelled'])
            alerts=[{'id':r['id'],'type':'low_stock','message':f"{r['name']} has {r['available']} {r['unit']} remaining at {r['location']}"} for r in report['inventoryStockData'] if r['stockStatus']!='Optimal']
            data={'kpis':{'todaySales':day['salesSummary']['totalRevenue'],'todayGrossProfit':day['salesSummary']['grossProfit'],'monthSales':report['salesSummary']['totalRevenue'],'monthGrossProfit':report['salesSummary']['grossProfit'],'rawMaterialValue':inventory['rawMaterialsValue'],'finishedStockValue':inventory['finishedGoodsValue'],'lowStockItems':inventory['lowStockItemsCount'],'pendingTransfers':pending.count()},'salesTrend':report['salesTrendData'],'topProducts':[{'name':p['product'],'sales':p['qty'],'revenue':p['revenue']} for p in sorted(report['productPerformanceData'],key=lambda p:p['revenue'],reverse=True)[:5]],'alerts':alerts}
            permissions=effective_permissions(u)
            allowed=lambda *codes:'*' in permissions or any(c in permissions for c in codes)
            if not allowed('sales.view','sales.invoice.view','reports.finance','reports.branch','reports.view'):
                for key in ['todaySales','todayGrossProfit','monthSales','monthGrossProfit']:data['kpis'].pop(key,None)
                data['salesTrend']=[];data['topProducts']=[]
            if not allowed('inventory.view','inventory.stock.view'):
                for key in ['rawMaterialValue','finishedStockValue','lowStockItems']:data['kpis'].pop(key,None)
                data['alerts']=[]
            if not allowed('transfers.view','inventory.transfer.view'):data['kpis'].pop('pendingTransfers',None)
            if mode=='alerts': data=data['alerts']
        elif mode=='cash-bank': data=reports.cash_bank(u)
        elif mode=='income':
            data=[{'id':e.pk,'date':e.date,'source':e.source,'reference':e.reference,'description':e.description,'amount':e.amount,'paymentMethod':e.account,'customerName':'','branchName':'','status':e.status} for e in scoped_erp(m.LedgerEntry.objects.filter(organization=u.organization,type='Inflow'),u)]
        elif mode=='receivables': data=reports.receivables(u)
        elif mode=='payables': data=reports.payables(u)
        elif mode=='payments':
            data=[{'id':p.pk,'date':p.date,'supplierName':p.bill.supplier.name,'billNumber':p.bill.billNumber,'amount':p.amount,'method':p.method,'reference':p.reference or p.bill.billNumber,'status':'Completed'} for p in scoped_erp(m.SupplierPayment.objects.filter(organization=u.organization),u).select_related('bill__supplier')]
        elif mode=='finance':
            cb=reports.cash_bank(u);entries=scoped_erp(m.LedgerEntry.objects.filter(organization=u.organization,date=localdate()),u)
            data={'cashBalance':cb['cashAccount']['currentBalance'],'bankBalance':cb['bankAccount']['currentBalance'],'todayIncome':sum(e.amount for e in entries.filter(type='Inflow')),'todayExpenses':sum(e.amount for e in entries.filter(type='Outflow')),'receivables':sum(r['outstanding'] for r in reports.receivables(u)),'payables':sum(r['outstanding'] for r in reports.payables(u))}
            from apps.hrms.models import PayrollRecord,SalaryAdvance
            payroll=PayrollRecord.objects.filter(employee_id__in=employee_ids(u),organization=u.organization,status='Approved')
            advances=SalaryAdvance.objects.filter(employee_id__in=employee_ids(u),organization=u.organization,status='Disbursed')
            data['payrollLiability']=sum(p.net for p in payroll)
            data['advanceReceivable']=sum(a.amount-a.repaid for a in advances)
        else: raise ValidationError('Unsupported projection.')
        return Response(svc.json_num(data))
    @transaction.atomic
    def post(self,request):
        from apps.accounts.models import Organization
        Organization.objects.select_for_update().get(pk=request.user.organization_id)
        inp=self.get_serializer(data=request.data);inp.is_valid(raise_exception=True);d=inp.validated_data;u=request.user
        if self.mode=='availability':
            v=svc.owned(m.Variant,d.get('variantId'),u);loc=svc.location(u,d.get('warehouseId'),'Warehouse');data=svc.availability(u,v,svc.integer(d.get('quantity')),loc)
        elif self.mode=='checkout':
            i=svc.checkout(u,d);return Response(svc.json_num({'invoice':s.InvoiceSerializer(i).data}),status=201)
        elif self.mode=='payments':
            bill=svc.owned(m.Bill,d.get('billId'),u);bill=m.Bill.objects.select_for_update().get(pk=bill.pk)
            amount=svc.D(d.get('amount'),True)
            if amount>s.BillSerializer(bill).get_balance(bill): raise ValidationError('Payment exceeds the bill balance.')
            reference=str(d.get('reference','')).strip()
            if len(reference)>120: raise ValidationError('Payment reference exceeds 120 characters.')
            if d.get('method','Bank') not in ['Cash','Bank','Card','UPI','Bank Transfer','Petty Cash']: raise ValidationError('Unsupported payment method.')
            p=m.SupplierPayment.objects.create(organization=u.organization,bill=bill,date=d.get('date') or localdate(),amount=amount,method=d.get('method','Bank'),reference=reference)
            bill.paid+=amount;bill.save();svc.ledger(u,amount,p.method,'Outflow',bill.billNumber,'Supplier payment','supplier_payment',p.pk,p.date);data={'id':p.pk,'amount':amount}
        else: raise ValidationError('Unsupported operation.')
        return Response(svc.json_num(data),status=201 if self.mode=='payments' else 200)

class BalanceView(Projection):
    read_permissions=['finance.view'];write_permissions=['finance.receivables','finance.payables']
    @transaction.atomic
    def patch(self,request,pk):
        target=svc.D(request.data.get('outstanding'))
        u=request.user
        if self.mode=='receivables':
            obj=svc.owned(m.Invoice,pk,u);obj=m.Invoice.objects.select_for_update().get(pk=obj.pk)
            returns=m.SalesReturn.objects.filter(line__invoice=obj).aggregate(n=m.models.Sum('refundAmount'))['n'] or svc.ZERO
            net=max(svc.ZERO,obj.total-returns)
        else:
            obj=svc.owned(m.Bill,pk,u);obj=m.Bill.objects.select_for_update().get(pk=obj.pk);net=max(svc.ZERO,obj.amount-svc.bill_credit(obj))
        if target>net: raise ValidationError('Outstanding balance cannot exceed the document total.')
        new_paid=net-target;delta=new_paid-obj.paid
        obj.paid=new_paid
        if isinstance(obj,m.Invoice): obj.status='Paid' if target==0 else 'Partially Paid' if new_paid else 'Unpaid'
        obj.save()
        flow='Inflow' if self.mode=='receivables' else 'Outflow'
        if delta<0: flow='Outflow' if flow=='Inflow' else 'Inflow'
        svc.ledger(u,abs(delta),'Bank',flow,getattr(obj,'invoiceNumber',None) or obj.billNumber,'Balance settlement/correction',self.mode,obj.pk)
        return Response({'detail':'Balance updated through a posted settlement.'})
    def delete(self,request,pk): raise ValidationError('Outstanding documents cannot be deleted. Settle or return the originating document.')
