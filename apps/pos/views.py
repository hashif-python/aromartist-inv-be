"""Mobile adapters: ERP remains the sole stock, invoice and accounting authority."""
import hashlib,json
from decimal import Decimal
from datetime import datetime,date
from zoneinfo import ZoneInfo
from django.conf import settings
from django.db import transaction
from django.db.models import Q,Sum
from django.utils import timezone
from django.contrib.auth import authenticate
from drf_spectacular.utils import extend_schema
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions
from rest_framework.exceptions import ValidationError,PermissionDenied,AuthenticationFailed
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken
from apps.accounts.permissions import has
from apps.accounts.access import location_ids,scope
from apps.accounts.scope_context import permission_context
from apps.accounts.serializers import ProfileSerializer
from apps.accounts.models import Organization
from apps.erp import models as e,services as s
from apps.erp.serializers import CustomerSerializer
from . import models as p

METHODS=['Cash','Card','UPI','Bank Transfer']

def require(user,*codes):
    if not has(user,*codes):raise PermissionDenied('Your account does not have permission for this action.')

def branches(user):
    qs=e.Location.objects.filter(organization=user.organization,kind='Branch',status='active')
    key='pos.access' if has(user,'pos.access') else 'sales.invoice.checkout' if has(user,'sales.invoice.checkout') else 'sales.pos'
    token=permission_context.set(key)
    try:return qs if scope(user)=='organization' else qs.filter(pk__in=location_ids(user))
    finally:permission_context.reset(token)

def branch(user,identifier):
    item=branches(user).filter(pk=identifier).first()
    if not item:raise PermissionDenied('Branch is outside your authorized scope.')
    return item

def invoices(user,b):
    qs=e.Invoice.objects.filter(organization=user.organization,branch=b).select_related('salesperson','branch').prefetch_related('lines')
    return qs if has(user,'pos.orders.branch') else qs.filter(salesperson=user)

def receipt(inv):
    sale=p.Sale.objects.filter(invoice=inv).first()
    tendered=sale.tendered if sale else inv.paid
    # Deliberately excludes formulation/cost snapshots and sensitive customer notes.
    returns=list(e.SalesReturn.objects.filter(line__invoice=inv).values('returnRef','qty','refundAmount','condition','reason','created_at','line__sku'))
    return dict(id=inv.pk,invoiceNumber=inv.invoiceNumber,branchId=inv.branch_id,branchName=inv.branch.name,business=inv.organization.name,tendered=tendered,change=max(Decimal("0"),tendered-inv.paid) if inv.paymentMethod=="Cash" else Decimal("0"),customerName=inv.customerName,customerMobile=inv.customerMobile,cashier=inv.salesperson.first_name or inv.salesperson.username,date=inv.date,createdAt=inv.created_at,status=inv.status,paymentMethod=inv.paymentMethod,subtotal=inv.subtotal,discount=inv.discount,tax=inv.tax,total=inv.total,paid=inv.paid,stockPosted=True,returns=returns,lines=[dict(id=l.pk,variantId=l.variant_id,name=l.productName,sku=l.sku,qty=l.qty,rate=l.rate,discount=l.discount,total=l.total,returned=l.returned) for l in inv.lines.all()])

def shift_summary(shift):
    inv=e.Invoice.objects.filter(pos_sale__shift=shift)
    cash=inv.filter(paymentMethod='Cash').aggregate(n=Sum('paid'))['n'] or s.ZERO
    noncash=inv.exclude(paymentMethod='Cash').aggregate(n=Sum('paid'))['n'] or s.ZERO
    refs=e.SalesReturn.objects.filter(pos_refund__shift=shift,refundMethod='Cash').values_list('returnRef',flat=True)
    refunds=e.LedgerEntry.objects.filter(organization=shift.organization,source='sales_return',reference__in=refs).aggregate(n=Sum('amount'))['n'] or s.ZERO
    ins=shift.movements.filter(kind='In').aggregate(n=Sum('amount'))['n'] or s.ZERO
    outs=shift.movements.filter(kind='Out').aggregate(n=Sum('amount'))['n'] or s.ZERO
    return dict(id=shift.pk,register=shift.register.name,branchId=shift.register.branch_id,openedAt=shift.opened_at,closedAt=shift.closed_at,closingRequested=shift.closingRequested,closedBy=shift.closedBy_id,opening=shift.opening,cashSales=cash,nonCash=noncash,cashRefunds=refunds,cashIn=ins,cashOut=outs,expected=shift.expected if shift.closed_at else shift.opening+cash-refunds+ins-outs,counted=shift.counted,difference=shift.difference)

@extend_schema(exclude=True)
class Login(APIView):
    permission_classes=[permissions.AllowAny];authentication_classes=[]
    throttle_classes=[ScopedRateThrottle];throttle_scope='login'
    def post(self,request):
        user=authenticate(username=request.data.get('username'),password=request.data.get('password'))
        if not user or not user.organization_id:raise AuthenticationFailed('Invalid ERP username or password.')
        require(user,'pos.access','sales.pos','sales.invoice.checkout')
        if not user.is_superuser and not has(user,'*') and not user.employees.filter(organization=user.organization,status='active').exists():raise PermissionDenied('Link this active cashier account to an employee first.')
        token=RefreshToken.for_user(user)
        return Response(dict(access=str(token.access_token),refresh=str(token),user=ProfileSerializer(user).data))

@extend_schema(exclude=True)
class Mobile(APIView):
    def initial(self,request,*args,**kwargs):
        super().initial(request,*args,**kwargs)
        require(request.user,'pos.access','sales.pos','sales.invoice.checkout')
        if not request.user.organization_id:raise PermissionDenied('Organization assignment is required.')
        if not request.user.is_superuser and not has(request.user,'*') and not request.user.employees.filter(organization=request.user.organization,status='active').exists():raise PermissionDenied('An active linked employee is required.')
    @transaction.atomic
    def post(self,request,section,pk=None):
        Organization.objects.select_for_update().get(pk=request.user.organization_id)
        return self.mutate(request,section,pk)
    @transaction.atomic
    def patch(self,request,section,pk=None):
        Organization.objects.select_for_update().get(pk=request.user.organization_id)
        return self.mutate(request,section,pk)
    def get(self,request,section,pk=None):
        u=request.user
        if section=='workspace':
            return Response(s.json_num(dict(timezone=settings.TIME_ZONE,businessDate=timezone.localdate(),paymentMethods=METHODS,permissions=ProfileSerializer(u).data['permissions'],branches=[dict(id=b.pk,name=b.name,warehouse=b.warehouse_id,warehouseName=b.warehouse.name if b.warehouse else None,salesLocation=b.pk) for b in branches(u).select_related('warehouse')])))
        b=branch(u,request.query_params.get('branchId'))
        search=request.query_params.get('search','').strip()[:120]
        if section in ['products','stock']:
            require(u,'pos.stock.view','inventory.stock.view')
            qs=e.Variant.objects.filter(organization=u.organization,status='active',productId__status='active').select_related('productId__fragranceId','bottleSizeId','concentrationId')
            if search:qs=qs.filter(Q(productId__name__icontains=search)|Q(sku__icontains=search)|Q(barcode__icontains=search)|Q(productId__fragranceId__name__icontains=search)|Q(bottleSizeId__name__icontains=search))
            if request.query_params.get('ids'):qs=qs.filter(pk__in=request.query_params['ids'].split(',')[:100])
            if request.query_params.get('category'):qs=qs.filter(productId__category=request.query_params['category'])
            stocks=dict(e.Stock.objects.filter(location=b,variant__isnull=False).values_list('variant_id','quantity'))
            rows=[dict(id=v.pk,name=v.productId.name,fragrance=v.productId.fragranceId.name if v.productId.fragranceId else '',sku=v.sku,barcode=v.barcode,bottleSize=v.bottleSizeId.name,concentration=v.concentrationId.name,category=v.productId.category,price=v.sellingPrice,available=stocks.get(v.pk,0),location=b.name) for v in qs.order_by('productId__name','sku')[:200]]
            return Response(s.json_num(rows))
        if section in ['orders','today','receipt','status']:
            require(u,'pos.order.view','sales.invoice.view','sales.view')
            qs=invoices(u,b)
            if section=='status':
                inv=qs.filter(checkoutKey=request.query_params.get('key')).first()
                return Response(s.json_num(dict(invoice=receipt(inv) if inv else None)))
            if pk:
                require(u,'pos.receipt.view','sales.invoice.view','sales.view')
                inv=qs.filter(pk=pk).first()
                if not inv:raise PermissionDenied('Invoice is outside your authorized scope.')
                return Response(s.json_num(receipt(inv)))
            if section=='today':qs=qs.filter(created_at__date=timezone.localdate())
            else:
                require(u,'pos.sales_history.view')
                for key,lookup in [('fromDate','date__gte'),('toDate','date__lte')]:
                    if request.query_params.get(key):
                        try:day=date.fromisoformat(request.query_params[key])
                        except ValueError:raise ValidationError('Use YYYY-MM-DD dates.')
                        qs=qs.filter(**{lookup:day})
            if search:qs=qs.filter(Q(invoiceNumber__icontains=search)|Q(customerName__icontains=search)|Q(lines__productName__icontains=search)).distinct()
            return Response(s.json_num([receipt(i) for i in qs.order_by('-created_at')[:100]]))
        if section=='dashboard':
            require(u,'pos.dashboard.view')
            qs=invoices(u,b).filter(created_at__date=timezone.localdate())
            totals=lambda rows:rows.aggregate(n=Sum('paid'))['n'] or 0
            return Response(s.json_num(dict(businessDate=timezone.localdate(),timezone=settings.TIME_ZONE,sales=qs.aggregate(n=Sum('total'))['n'] or 0,orders=qs.count(),cash=totals(qs.filter(paymentMethod='Cash')),other=totals(qs.exclude(paymentMethod='Cash')),drafts=p.Draft.objects.filter(cashier=u,branch=b,status='Draft').count(),returns=e.SalesReturn.objects.filter(line__invoice__in=qs).aggregate(n=Sum('refundAmount'))['n'] or 0,recent=[receipt(i) for i in qs.order_by('-created_at')[:5]])))
        if section=='customers':
            require(u,'sales.customer.view','customers.quick_add','customers.manage')
            qs=e.Customer.objects.filter(organization=u.organization)
            if search:qs=qs.filter(Q(name__icontains=search)|Q(mobile__icontains=search))
            return Response(s.json_num(list(qs.order_by('name').values('id','name','mobile','email','address')[:100])))
        if section=='drafts':
            require(u,'pos.order.edit_draft')
            rows=p.Draft.objects.filter(organization=u.organization,cashier=u,branch=b,status='Draft')
            return Response(s.json_num([dict(id=d.pk,label=d.label,payload=d.payload,revision=d.revision,status=d.status) for d in rows.order_by('-updated_at')[:100]]))
        if section in ['registers','shifts']:
            require(u,'pos.register.open','pos.register.close')
            if section=='registers':return Response(list(p.Register.objects.filter(organization=u.organization,branch=b,active=True).values('id','name','discrepancyLimit')))
            return Response(s.json_num([shift_summary(x) for x in p.Shift.objects.filter(organization=u.organization,register__branch=b).filter(Q(cashier=u)|Q(closingRequested=True) if has(u,'pos.register.approve_discrepancy') else Q(cashier=u)).select_related('register').order_by('-opened_at')[:30]]))
        raise ValidationError('Unsupported POS resource.')

    def mutate(self,request,section,pk):
        u=request.user;data=request.data;b=branch(u,data.get('branchId'))
        if section=='customers':
            require(u,'sales.customer.create','customers.quick_add','customers.manage')
            if request.method=='PATCH':require(u,'sales.customer.edit','customers.manage')
            instance=e.Customer.objects.filter(organization=u.organization,pk=pk).first() if pk else None
            if pk and not instance:raise PermissionDenied('Customer not found.')
            serializer=CustomerSerializer(instance,data={k:v for k,v in data.items() if k in ['name','mobile','email','address']},partial=bool(pk),context={'request':request})
            serializer.is_valid(raise_exception=True);obj=serializer.save(organization=u.organization)
            return Response(s.json_num(dict(id=obj.pk,name=obj.name,mobile=obj.mobile,email=obj.email,address=obj.address)),status=200 if pk else 201)
        if section=='drafts':
            require(u,'pos.order.edit_draft')
            d=p.Draft.objects.select_for_update().filter(pk=pk,cashier=u,branch=b,organization=u.organization).first() if pk else None
            if pk and not d:raise PermissionDenied('Draft not found.')
            if d and (d.status!='Draft' or data.get('revision')!=d.revision):raise ValidationError('Draft changed or is finalized. Reload before editing.')
            if data.get('cancel'):
                require(u,'pos.order.cancel')
                if not d:raise ValidationError('Select a saved draft.')
                d.status='Cancelled'
            else:
                payload=data.get('payload')
                if not isinstance(payload,dict) or not isinstance(payload.get('cart'),list) or not 1<=len(payload['cart'])<=100:raise ValidationError('A draft needs 1–100 cart lines.')
                for row in payload['cart']:
                    if not isinstance(row,dict):raise ValidationError('Invalid cart line.')
                    s.integer(row.get('qty'))
                    if not e.Variant.objects.filter(organization=u.organization,pk=row.get('id')).exists():raise ValidationError('Unknown variant.')
                if not d:d=p.Draft(organization=u.organization,cashier=u,branch=b)
                d.payload=payload;d.label=str(data.get('label','Held sale'))[:100]
            if pk:d.revision+=1
            d.save();return Response(s.json_num(dict(id=d.pk,label=d.label,payload=d.payload,revision=d.revision,status=d.status)),status=200 if pk else 201)
        if section=='checkout':
            require(u,'sales.invoice.checkout','sales.pos')
            if not b.warehouse_id or b.warehouse.status!='active':raise ValidationError('Configure an active warehouse for this branch before checkout.')
            key=data.get('checkoutKey')
            if not isinstance(key,str) or not 8<=len(key)<=64:raise ValidationError('A stable checkout idempotency key is required.')
            if data.get('paymentMethod') not in METHODS:raise ValidationError('Mobile supports Cash, Card, UPI and Bank Transfer. These record externally collected payments.')
            if not isinstance(data.get('cart'),list) or len(data['cart'])>100 or any(not isinstance(row,dict) for row in data['cart']):raise ValidationError('Invalid cart.')
            if s.D(data.get('discount',0)) or any(s.D(row.get('discount',0)) for row in data['cart']):require(u,'pos.discount.apply')
            existing=e.Invoice.objects.filter(organization=u.organization,checkoutKey=key).first()
            shift=p.Shift.objects.select_for_update().filter(cashier=u,register__branch=b,closed_at=None).first()
            if shift and shift.closingRequested and not existing:raise ValidationError('Register reconciliation is awaiting supervisor approval.')
            if not shift and not existing:raise ValidationError('Open your register shift before checkout.')
            draft=p.Draft.objects.select_for_update().filter(pk=data.get('draftId'),cashier=u,branch=b).first() if data.get('draftId') else None
            if data.get('draftId') and (not draft or (draft.status!='Draft' and not (existing and draft.invoice_id==existing.pk))):raise ValidationError('Draft is unavailable or finalized.')
            if draft and draft.status=='Draft' and data.get('revision')!=draft.revision:raise ValidationError('Draft changed. Reload before checkout.')
            inv=s.checkout(u,{**data,'branchId':b.pk})
            tendered=s.D(data.get('tendered',inv.total))
            if inv.paymentMethod=='Cash' and tendered<inv.total:raise ValidationError('Cash received is less than the invoice total.')
            if not existing:
                sale,_=p.Sale.objects.get_or_create(invoice=inv,defaults=dict(organization=u.organization,shift=shift,tendered=tendered))
                sale.tendered=tendered;sale.save(update_fields=['tendered'])
            if draft and draft.status=='Draft':draft.status='Posted';draft.invoice=inv;draft.revision+=1;draft.save()
            return Response(s.json_num(dict(invoice=receipt(inv))),status=200 if existing else 201)
        if section=='returns':
            require(u,'sales.return.create','sales.returns');require(u,'pos.refund.process')
            inv=invoices(u,b).filter(invoiceNumber=data.get('invoiceNumber')).first()
            if not inv:raise PermissionDenied('Original invoice is outside your authorized scope.')
            shift=p.Shift.objects.select_for_update().filter(cashier=u,register__branch=b,closed_at=None).first()
            if not shift:raise ValidationError('Open a register shift before refunding.')
            if data.get('refundMethod','Cash') not in METHODS:raise ValidationError('Unsupported refund method.')
            key=data.get('returnKey')
            if not isinstance(key,str) or not 8<=len(key)<=64:raise ValidationError('A stable refund request key is required.')
            fingerprint=hashlib.sha256(json.dumps({k:data.get(k) for k in ['invoiceNumber','sku','qty','reason','condition','refundMethod']},sort_keys=True).encode()).hexdigest()
            prior=p.Refund.objects.filter(organization=u.organization,requestKey=key).first()
            if prior:
                if prior.cashier_id!=u.pk or prior.fingerprint!=fingerprint:raise ValidationError('Refund request key was already used for another return.')
                return Response(s.json_num(dict(id=prior.returned_id,reference=prior.returned.returnRef,refund=prior.returned.refundAmount)))
            ret=s.sales_return(u,data)
            journal=p.Refund.objects.get(returned=ret);journal.requestKey=key;journal.fingerprint=fingerprint;journal.save()
            return Response(s.json_num(dict(id=ret.pk,reference=ret.returnRef,refund=ret.refundAmount)),status=201)
        if section=='shifts':
            if not pk:
                require(u,'pos.register.open')
                reg=p.Register.objects.select_for_update().filter(pk=data.get('registerId'),organization=u.organization,branch=b,active=True).first()
                if not reg:raise ValidationError('Choose an authorized active register.')
                if p.Shift.objects.filter(Q(register=reg)|Q(cashier=u),closed_at=None).exists():raise ValidationError('An active register/cashier shift already exists.')
                shift=p.Shift.objects.create(organization=u.organization,register=reg,cashier=u,opening=s.D(data.get('opening',0)))
                return Response(s.json_num(shift_summary(shift)),status=201)
            shift=p.Shift.objects.select_for_update().filter(pk=pk,organization=u.organization,register__branch=b,closed_at=None).filter(Q(cashier=u)|Q(closingRequested=True) if has(u,'pos.register.approve_discrepancy') else Q(cashier=u)).first()
            if not shift:raise ValidationError('Your active shift was not found.')
            if data.get('action')=='cash':
                if shift.closingRequested:raise ValidationError('Cash adjustments are locked while reconciliation is pending.')
                require(u,'pos.register.cash_adjust')
                amount=s.D(data.get('amount'),True);kind=data.get('kind');reason=str(data.get('reason','')).strip()
                if kind not in ['In','Out'] or not reason or len(reason)>250:raise ValidationError('Choose In/Out and a reason up to 250 characters.')
                if kind=='Out' and amount>shift_summary(shift)['expected']:raise ValidationError('Cash out exceeds expected cash.')
                entry=e.LedgerEntry.objects.create(organization=u.organization,date=timezone.localdate(),account='Cash',type='Inflow' if kind=='In' else 'Outflow',description=reason,amount=amount)
                p.CashMovement.objects.create(organization=u.organization,shift=shift,cashier=u,kind=kind,amount=amount,reason=reason,ledger=entry)
            elif data.get('action')=='close':
                require(u,'pos.register.close')
                expected=shift_summary(shift)['expected'];counted=shift.counted if shift.closingRequested and shift.cashier_id!=u.pk else s.D(data.get('counted'));diff=counted-expected
                shift.expected=expected;shift.counted=counted;shift.difference=diff
                if abs(diff)>shift.register.discrepancyLimit and not has(u,'pos.register.approve_discrepancy'):
                    shift.closingRequested=True
                else:
                    shift.closed_at=timezone.now();shift.closedBy=u;shift.closingRequested=False
                shift.save()
            else:raise ValidationError('Choose cash or close.')
            return Response(s.json_num(shift_summary(shift)))
        raise ValidationError('This finalized resource is read-only; use an authorized return.')
