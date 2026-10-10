"""Transactional ERP posting. Caller must own an atomic transaction for mutations."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from collections import defaultdict
from datetime import date
from django.utils import timezone
import uuid
import hashlib
import json
from django.db import transaction
from django.db.models import Q, Sum
from rest_framework.exceptions import ValidationError, PermissionDenied
from apps.accounts.permissions import has
from .models import *
from .category_utils import material_type

ZERO=Decimal('0')
def D(value,positive=False):
    try: n=Decimal(str(value))
    except (InvalidOperation,TypeError,ValueError): raise ValidationError('Enter a valid number.')
    if not n.is_finite() or n<0 or (positive and n<=0) or n>Decimal('9999999999999'): raise ValidationError('Enter a finite, positive number within supported limits.')
    if n.as_tuple().exponent < -4: raise ValidationError('Use at most four decimal places.')
    return n

def integer(value):
    n=D(value,True)
    if n != n.to_integral_value() or n>2147483647: raise ValidationError('A positive whole number is required.')
    return int(n)

def cash(n): return n.quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
def number(prefix,organization,day=None):
    from apps.common.services.code_generator import allocate
    prefix={'TR':'TRF'}.get(prefix,prefix)
    return allocate(organization,f'workflow.{prefix}',prefix,True,model=Movement,field='reference',day=day)
def json_num(value):
    if isinstance(value,Decimal): return float(value)
    if isinstance(value,list): return [json_num(v) for v in value]
    if isinstance(value,dict): return {k:json_num(v) for k,v in value.items()}
    return value

def owned(model,value,user,field='pk'):
    from apps.accounts.access import scoped_erp
    try: return scoped_erp(model.objects.filter(organization=user.organization),user).get(**{field:value})
    except (model.DoesNotExist,ValueError): raise ValidationError({field:f'{model.__name__} does not exist in your organization.'})

def location(user,value=None,kind=None):
    if value:
        qs=Location.objects.filter(organization=user.organization)
        obj=qs.filter(Q(pk=value)|Q(name=value)|Q(code=value)).first()
    else:
        obj=user.branch if kind=='Branch' else user.warehouse
    if not obj or (kind and obj.kind!=kind) or obj.status!='active': raise ValidationError('Select an active location of the required type.')
    enforce_location(user,obj)
    return obj

def enforce_location(user,obj):
    from apps.accounts.access import scope,location_ids
    if scope(user)=='organization': return
    # Assignment is authoritative; unassigned staff cannot act on arbitrary locations.
    if obj.pk not in location_ids(user): raise PermissionDenied('This location is not assigned to your account.')

def scoped_stocks(user):
    qs=Stock.objects.filter(organization=user.organization)
    from apps.accounts.access import scoped_erp
    qs=scoped_erp(qs,user)
    return qs.select_related('location','material','variant__productId','variant__concentrationId','variant__bottleSizeId')

def stock_for(user,loc,item):
    field='material' if isinstance(item,Material) else 'variant'
    # Lock the parent catalog record even if the balance row is being created.
    type(item).objects.select_for_update().get(pk=item.pk)
    s,_=Stock.objects.get_or_create(organization=user.organization,location=loc,**{field:item})
    return Stock.objects.select_for_update().get(pk=s.pk)

def post_stock(user,loc,item,delta,kind,ref,reason=''):
    s=stock_for(user,loc,item)
    old=s.quantity
    if old+delta<0: raise ValidationError(f'Insufficient {item.name} stock at {loc.name}. Available: {old}.')
    if isinstance(item,Variant) and delta!=delta.to_integral_value(): raise ValidationError('Finished stock quantity must be a whole number.')
    s.quantity=old+delta;s.save(update_fields=['quantity','updated_at'])
    Movement.objects.create(organization=user.organization,stock=s,transaction=kind,reference=ref,delta=delta,previousStock=old,newStock=s.quantity,reason=reason,user=user)
    return s

def ledger(user,amount,method,flow,ref,description,source,source_id,when=None):
    if amount:
        return LedgerEntry.objects.create(organization=user.organization,date=when or date.today(),account='Cash' if method in ['Cash','Petty Cash'] else 'Bank',type=flow,reference=ref,description=description,amount=amount,source=source,sourceId=source_id)

def formula_preview(user,data):
    frag=owned(Fragrance,data.get('fragranceId'),user)
    conc=owned(Concentration,data.get('concentrationId'),user)
    size=owned(BottleSize,data.get('bottleSizeId'),user)
    solvent=Material.objects.filter(Q(categoryRef__categoryType='Solvent')|Q(categoryRef__isnull=True,category='Solvent'),organization=user.organization,status='active',unit='ml').order_by('code').first()
    if not solvent: raise ValidationError('Create an active Solvent raw material before defining formulas.')
    oil=frag.perfumeOilId
    oilqty=(size.volumeMl*conc.oilPercentage/100).quantize(Decimal('.0001'))
    solventqty=size.volumeMl-oilqty
    def row(mat,qty,required=True): return {'materialId':mat.pk,'name':mat.name,'type':mat.category,'qty':qty,'unit':mat.unit,'rate':mat.currentCost,'cost':cash(qty*mat.currentCost),'required':required}
    ingredients=[row(oil,oilqty),row(solvent,solventqty)]
    packaging=[row(size.bottleMaterialRef,Decimal(1))]
    for category in ['Pump','Cap','Label','Pouch','Carry Bag']:
        mat=Material.objects.filter(organization=user.organization,category=category,status='active').order_by('code').first()
        if mat: packaging.append(row(mat,Decimal(1),category not in ['Pouch','Carry Bag']))
    if 'packaging' in data:
        packaging=[]
        seen_packaging=set()
        for entry in data['packaging']:
            mat=owned(Material,entry.get('materialId'),user)
            if mat.pk in seen_packaging or mat.status!='active' or material_type(mat)!='Packaging': raise ValidationError('Choose unique active packaging materials.')
            seen_packaging.add(mat.pk)
            packaging.append(row(mat,D(entry.get('qty',1),True),entry.get('required',True)))
    extras={k:D(data.get(k,0)) for k in ['laborCost','cleaningAllocation','otherCost']}
    return {**data,**extras,'oilQty':oilqty,'solventQty':solventqty,'ingredients':ingredients,'packaging':packaging,'estimatedUnitCost':cash(sum(r['cost'] for r in ingredients+packaging)+sum(extras.values()))}

def save_formula(user,data,instance=None):
    if data.get("percentageRecipe") or (instance and instance.percentageRecipe):
        from .workflow import save_percentage_formula
        return save_percentage_formula(user,data,instance)
    preview=formula_preview(user,data)
    for field in ['oilQty','solventQty']:
        if field in data and D(data[field]) != preview[field]: raise ValidationError('Oil and solvent quantities must match the selected concentration and bottle volume.')
    if instance and Batch.objects.filter(formula=instance).exists():
        raise ValidationError('This formula is used by a production batch. Create a new formula version to preserve the recipe.')
    fields={k:preview[k] for k in ['oilQty','solventQty','laborCost','cleaningAllocation','otherCost','estimatedUnitCost']}
    for key,model in [('fragranceId',Fragrance),('concentrationId',Concentration),('bottleSizeId',BottleSize)]: fields[key]=owned(model,data[key],user)
    fields.update(version=data.get('version','v1.0'),status=data.get('status','active'),effectiveDate=data.get('effectiveDate') or date.today())
    if instance:
        for k,v in fields.items(): setattr(instance,k,v)
        instance.save();instance.lines.all().delete()
    else: instance=Formula.objects.create(organization=user.organization,**fields)
    for group in ['ingredients','packaging']:
        for r in preview[group]: FormulaLine.objects.create(organization=user.organization,formula=instance,material_id=r['materialId'],group=group,qty=r['qty'],rate=r['rate'],required=r['required'])
    return instance

def availability(user,variant,qty,loc):
    rows=[]
    for line in recipe_lines(variant):
        available=Stock.objects.filter(location=loc,material=line.material).aggregate(n=Sum('quantity'))['n'] or ZERO
        required=line.qty*qty
        rows.append({'materialId':line.material_id,'name':line.material.name,'unit':line.material.unit,'required':f'{required} {line.material.unit}','available':f'{available} {line.material.unit}','reqVal':required,'availableVal':available,'status':'Available' if available>=required else 'Insufficient'})
    if not rows: raise ValidationError('The variant formula contains no materials.')
    return rows

def create_batch(user,data):
    v=owned(Variant,data.get('productVariantId'),user)
    wh=location(user,data.get('warehouseId') or data.get('warehouseName'),'Warehouse')
    qty=integer(data.get('plannedQty'))
    f=v.formulaId
    rows=availability(user,v,qty,wh)
    if any(r['status']=='Insufficient' for r in rows): raise ValidationError({'detail':'Insufficient materials for planned output.','materials':json_num(rows)})
    overhead=v.additionalCost if f.percentageRecipe else f.laborCost+f.cleaningAllocation+f.otherCost
    unit=cash(sum(l.qty*l.material.currentCost for l in recipe_lines(v))+overhead)
    b=Batch.objects.create(organization=user.organization,batchNo='',variant=v,warehouse=wh,formula=f,date=data.get('date') or date.today(),plannedQty=qty,unitCost=unit,totalCost=unit*qty,overheadCost=overhead*qty,notes=data.get('notes',''))
    for l in recipe_lines(v):
        Consumption.objects.create(organization=user.organization,batch=b,material=l.material,standard=l.qty*qty,actual=l.qty*qty,rate=l.material.currentCost)
    return b

def complete_batch(user,b,data):
    enforce_location(user,b.warehouse)
    if b.status!='Draft': raise ValidationError('Only a Draft batch can be completed, once.')
    actual_qty=integer(data.get('actualProduced',b.plannedQty))
    supplied={r.get('materialId'):r for r in data.get('actualConsumption',[])}
    lines=list(b.consumptions.select_related('material').order_by('material_id'))
    if supplied and set(supplied)!={l.material_id for l in lines}: raise ValidationError('Actual consumption must include each recipe material exactly once.')
    if len(supplied)!=len(data.get('actualConsumption',[])): raise ValidationError('Duplicate consumption materials are not allowed.')
    total=b.overheadCost
    for l in lines:
        actual=D(supplied[l.material_id].get('actual'),True) if supplied else l.standard
        post_stock(user,b.warehouse,l.material,-actual,'PRODUCTION_CONSUMPTION',b.batchNo)
        l.actual=actual;l.save(update_fields=['actual']);total+=actual*l.rate
    b.producedQty=actual_qty;b.totalCost=cash(total);b.unitCost=cash(total/actual_qty);b.status='Completed';b.save()
    v=Variant.objects.select_for_update().get(pk=b.variant_id)
    existing=Stock.objects.filter(variant=v).aggregate(n=Sum('quantity'))['n'] or ZERO
    v.costPrice=cash((existing*v.costPrice+b.totalCost)/(existing+actual_qty));v.save(update_fields=['costPrice'])
    post_stock(user,b.finishedWarehouse or b.warehouse,v,Decimal(actual_qty),'PRODUCTION_OUTPUT',b.batchNo)
    return b

def transfer_create(user,data):
    src=location(user,data.get('sourceName'),data.get('sourceType'))
    # Destination may be any active organization location; receipt requires destination assignment.
    dest=Location.objects.filter(organization=user.organization,name=data.get('destName'),kind=data.get('destType'),status='active').first()
    if not dest or dest==src: raise ValidationError('Select a different valid destination.')
    items=data.get('items',[])
    if not items: raise ValidationError('At least one transfer item is required.')
    t=Transfer.objects.create(organization=user.organization,transferNo='',source=src,destination=dest,date=data.get('date') or date.today(),notes=data.get('notes',''),requestedBy=user)
    seen=set()
    for r in items:
        model=Material if r.get('itemType')=='Raw Material' else Variant
        item=owned(model,r.get('itemId'),user)
        if (model.__name__,item.pk) in seen: raise ValidationError('Duplicate transfer items are not allowed.')
        seen.add((model.__name__,item.pk))
        qty=D(r.get('requestedQty'),True)
        if model==Variant: integer(qty)
        if stock_for(user,src,item).quantity<qty: raise ValidationError('Insufficient stock for requested transfer.')
        TransferLine.objects.create(organization=user.organization,transfer=t,**{'material' if model==Material else 'variant':item},requestedQty=qty)
    return t

def transfer_action(user,t,action,data):
    if action=='approve':
        if t.status!='Requested': raise ValidationError('Only a requested transfer can be approved.')
        t.status='Approved';t.approvedBy=user;t.approvedAt=timezone.now()
    elif action=='dispatch':
        enforce_location(user,t.source)
        if t.status!='Approved': raise ValidationError('Approve the transfer before dispatching.')
        for l in t.lines.select_related('material','variant').order_by('id'):
            post_stock(user,t.source,l.material or l.variant,-l.requestedQty,'TRANSFER_DISPATCH',t.transferNo)
            l.dispatchedQty=l.requestedQty;l.save()
        t.status='Dispatched';t.dispatchedBy=user;t.dispatchedAt=timezone.now()
    elif action=='receive':
        enforce_location(user,t.destination)
        if t.status!='Dispatched': raise ValidationError('Only a dispatched transfer can be received, once.')
        supplied={r.get('id') or r.get('itemId'):r for r in data.get('items',[])}
        lines=list(t.lines.select_related('material','variant').order_by('id'))
        valid_keys={k for l in lines for k in [l.pk,l.material_id or l.variant_id]}
        if len(supplied)!=len(data.get('items',[])) or any(k not in valid_keys for k in supplied): raise ValidationError('Invalid or duplicate receipt items.')
        for l in lines:
            r=supplied.get(l.pk,supplied.get(l.material_id or l.variant_id,{}))
            received=D(r.get('receivedQty',l.dispatchedQty));damaged=D(r.get('damagedQty',0))
            if received+damaged != l.dispatchedQty: raise ValidationError('Received plus damaged quantity must equal dispatched quantity.')
            post_stock(user,t.destination,l.material or l.variant,received,'TRANSFER_RECEIPT',t.transferNo)
            l.receivedQty=received;l.damagedQty=damaged;l.save()
        t.status='Received';t.receivedBy=user;t.receivedAt=timezone.now()
    elif action=='cancel':
        enforce_location(user,t.source)
        if t.status not in ['Requested','Approved']: raise ValidationError('Only an undispatched transfer may be cancelled.')
        t.status='Cancelled'
    t.save();return t

def create_po(user,data):
    sup=owned(Supplier,data.get('supplierName'),user,'name')
    wh=location(user,data.get('warehouseName'),'Warehouse')
    if not data.get('items'): raise ValidationError('At least one line item is required.')
    po=PurchaseOrder.objects.create(organization=user.organization,poNumber='',supplier=sup,warehouse=wh,orderDate=data.get('orderDate') or date.today(),expectedDate=data.get('expectedDate') or date.today(),notes=data.get('notes',''))
    seen=set()
    for r in data['items']:
        mat=Material.objects.filter(organization=user.organization).filter(Q(pk=r.get('material'))|Q(name=r.get('material'))|Q(code=r.get('material'))).first()
        if not mat: raise ValidationError('Select an existing raw material.')
        if mat.pk in seen: raise ValidationError('Use one line per material.')
        seen.add(mat.pk)
        qty=D(r.get('qty'),True);rate=D(r.get('rate'));disc=D(r.get('discount',0));tax=D(r.get('tax',0))
        if disc>qty*rate: raise ValidationError('Line discount exceeds the line amount.')
        PurchaseLine.objects.create(organization=user.organization,order=po,material=mat,qty=qty,rate=rate,discount=disc,tax=tax)
        po.subtotal+=qty*rate;po.discountTotal+=disc;po.taxTotal+=tax
    po.grandTotal=cash(po.subtotal-po.discountTotal+po.taxTotal);po.save();return po

def create_grn(user,data):
    po=owned(PurchaseOrder,data.get('poNumber'),user,'poNumber')
    po=PurchaseOrder.objects.select_for_update().get(pk=po.pk)
    enforce_location(user,po.warehouse)
    if po.status=='Completed': raise ValidationError('This purchase order is already fully received.')
    if not data.get('items'): raise ValidationError('Receipt items are required.')
    note=data.get('deliveryNoteNo','').strip()
    if not note: raise ValidationError('Delivery note is required.')
    rec=Receipt.objects.create(organization=user.organization,grnNumber='',order=po,receiveDate=data.get('receiveDate') or date.today(),deliveryNoteNo=note,status='Completed')
    seen=set()
    for r in data['items']:
        line=po.lines.select_related('material').filter(Q(material__name=r.get('material'))|Q(material_id=r.get('materialId'))).first()
        if not line or line.pk in seen: raise ValidationError('Invalid or duplicate purchase line.')
        seen.add(line.pk)
        current=D(r.get('currentReceived'),True);accepted=D(r.get('acceptedQty'));rejected=D(r.get('rejectedQty',0))
        if accepted+rejected!=current or line.received+current>line.qty: raise ValidationError('Receipt quantities exceed the order or accepted plus rejected differs from received.')
        unit=D(r.get('unitCost',line.rate))
        post_stock(user,po.warehouse,line.material,accepted,'PURCHASE_RECEIPT',rec.grnNumber)
        mat=Material.objects.select_for_update().get(pk=line.material_id)
        total_stock=Stock.objects.filter(material=mat).aggregate(n=Sum('quantity'))['n'] or ZERO
        if total_stock>0: mat.currentCost=((total_stock-accepted)*mat.currentCost+accepted*unit)/total_stock;mat.currentCost=mat.currentCost.quantize(Decimal('.0001'));mat.save()
        ReceiptLine.objects.create(organization=user.organization,receipt=rec,orderLine=line,currentReceived=current,acceptedQty=accepted,rejectedQty=rejected,unitCost=unit)
        line.received+=current;line.save()
    if any(l.received<l.qty for l in po.lines.all()): rec.status='Partial Receipt';po.status='Partially Received'
    else: po.status='Completed'
    rec.save();po.save();return rec

def create_purchase_return(user,data):
    sup=owned(Supplier,data.get('supplierName'),user,'name')
    mat=owned(Material,data.get('material'),user,'name')
    wh=location(user,data.get('warehouseName'),'Warehouse')
    ref=data.get('linkedRef','')
    # Return must refer to a received purchase order from this supplier/location.
    linked=ref.split(' / ')[0]
    receipt=Receipt.objects.filter(organization=user.organization,grnNumber=linked,order__supplier=sup,order__warehouse=wh).first()
    if receipt: linked=receipt.order.poNumber
    po=PurchaseOrder.objects.select_for_update().filter(organization=user.organization,supplier=sup,warehouse=wh,poNumber=linked).first()
    if not po: raise ValidationError('Use a received GRN or purchase order number for this supplier and warehouse.')
    line=po.lines.filter(material=mat).first()
    if not line: raise ValidationError('This material is not included in the referenced order.')
    accepted=ReceiptLine.objects.filter(orderLine=line).aggregate(n=Sum('acceptedQty'))['n'] or ZERO
    returned=PurchaseReturn.objects.filter(organization=user.organization,linkedRef=po.poNumber,material=mat).aggregate(n=Sum('qty'))['n'] or ZERO
    qty=D(data.get('qty'),True)
    if qty+returned>accepted: raise ValidationError('Return quantity exceeds accepted goods.')
    rate=line.rate
    r=PurchaseReturn.objects.create(organization=user.organization,returnNumber='',supplier=sup,warehouse=wh,material=mat,linkedRef=po.poNumber,date=data.get('date') or date.today(),qty=qty,unitCost=rate,totalAmount=cash(qty*rate),reason=data.get('reason',''))
    if not r.reason.strip(): raise ValidationError('Return reason is required.')
    post_stock(user,wh,mat,-qty,'PURCHASE_RETURN',r.returnNumber,r.reason)
    return r

def checkout(user,data):
    loc=location(user,data.get('branchId') or data.get('branchName'),'Branch')
    cart=data.get('cart',[])
    key=str(data.get('checkoutKey','')).strip()
    fingerprint=''
    if key:
        if len(key)>64: raise ValidationError('Checkout request key is too long.')
        # Serialize retries from this operator; stock locks still arbitrate other operators.
        from django.contrib.auth import get_user_model
        get_user_model().objects.select_for_update().get(pk=user.pk)
        relevant={'branch':loc.pk,'customer':data.get('customerId'),'mobile':data.get('customerMobile'),'discount':str(data.get('discount',0)),'method':data.get('paymentMethod','Cash'),'items':[{'id':row.get('id') or row.get('variantId'),'qty':str(row.get('qty')),'discount':str(row.get('discount',0))} for row in cart]}
        fingerprint=hashlib.sha256(json.dumps(relevant,sort_keys=True).encode()).hexdigest()
        existing=Invoice.objects.filter(organization=user.organization,checkoutKey=key).first()
        if existing:
            if existing.salesperson_id!=user.pk or existing.branch_id!=loc.pk or existing.checkoutFingerprint!=fingerprint: raise ValidationError('This checkout request key was already used for a different sale.')
            return existing
    if not cart: raise ValidationError('Cart cannot be empty.')
    customer=None
    if data.get('customerId') and data['customerId']!='cust-walkin': customer=owned(Customer,data['customerId'],user)
    elif data.get('customerMobile') and data['customerMobile']!='0000000000': customer=Customer.objects.filter(organization=user.organization,mobile=data['customerMobile']).first()
    method=data.get('paymentMethod','Cash')
    if method not in ['Cash','Card','Bank','UPI','Credit','Bank Transfer','Split']: raise ValidationError('Unsupported payment method.')
    inv=Invoice.objects.create(organization=user.organization,invoiceNumber='',branch=loc,customer=customer,customerName=customer.name if customer else 'Walk-in Customer',customerMobile=customer.mobile if customer else '',salesperson=user,date=date.today(),paymentMethod=method,checkoutKey=key,checkoutFingerprint=fingerprint)
    seen=set()
    for r in sorted(cart,key=lambda r:r.get('id','')):
        v=owned(Variant,r.get('id') or r.get('variantId'),user)
        v=Variant.objects.select_for_update().get(pk=v.pk)
        if v.status!='active': raise ValidationError('Inactive products cannot be sold.')
        if v.pk in seen: raise ValidationError('Duplicate cart lines are not allowed.')
        seen.add(v.pk)
        qty=integer(r.get('qty'));disc=D(r.get('discount',0))
        total=v.sellingPrice*qty-disc
        if total<0 or total/qty<v.minSellingPrice: raise ValidationError('Line discount breaches minimum selling price.')
        InvoiceLine.objects.create(organization=user.organization,invoice=inv,variant=v,productName=f'{v.productId.name} {v.bottleSizeId.name} {v.concentrationId.code}',sku=v.sku,qty=qty,rate=v.sellingPrice,discount=disc,total=total,costSnapshot=v.costPrice)
        post_stock(user,loc,v,-Decimal(qty),'SALE',inv.invoiceNumber)
        inv.subtotal+=total
    inv.discount=D(data.get('discount',0))
    if inv.discount>inv.subtotal: raise ValidationError('Order discount exceeds subtotal.')
    for l in inv.lines.select_related('variant'):
        allocated=inv.discount*l.total/inv.subtotal if inv.subtotal else ZERO
        if (l.total-allocated)/l.qty<l.variant.minSellingPrice: raise ValidationError('Order discount breaches minimum selling price.')
        l.total=cash(l.total-allocated);l.save(update_fields=['total'])
    inv.total=cash(inv.subtotal-inv.discount)
    # Tax is zero in the uploaded POS, never accept a client supplied tax/total.
    inv.paid=ZERO if method=='Credit' else inv.total
    if method=='Credit' and not customer: raise ValidationError('A registered customer is required for credit sales.')
    inv.status='Unpaid' if method=='Credit' else 'Paid';inv.save()
    ledger(user,inv.paid,method,'Inflow',inv.invoiceNumber,'POS sale','invoice',inv.pk)
    return inv

def sales_return(user,data):
    inv=owned(Invoice,data.get('invoiceNumber'),user,'invoiceNumber')
    inv=Invoice.objects.select_for_update().get(pk=inv.pk)
    enforce_location(user,inv.branch)
    l=inv.lines.select_for_update().filter(sku=data.get('sku')).first()
    if not l: raise ValidationError('The selected SKU is not on this invoice.')
    qty=integer(data.get('qty'))
    if l.returned+qty>l.qty: raise ValidationError('Return exceeds the remaining sold quantity.')
    condition=data.get('condition','Sellable')
    if condition not in ['Sellable','Damaged','Unsellable','Opened']: raise ValidationError('Unsupported return condition.')
    reason=data.get('reason','').strip()
    if not reason: raise ValidationError('Return reason is required.')
    refund=cash(l.total*qty/l.qty)
    # Last partial return clears rounding residual to never refund more than the line.
    prior=SalesReturn.objects.filter(line=l).aggregate(n=Sum('refundAmount'))['n'] or ZERO
    if l.returned+qty==l.qty: refund=l.total-prior
    ret=SalesReturn.objects.create(organization=user.organization,returnRef='',line=l,date=date.today(),qty=qty,condition=condition,reason=reason,refundMethod=data.get('refundMethod','Cash'),refundAmount=refund)
    if condition=='Sellable': post_stock(user,inv.branch,l.variant,Decimal(qty),'SALES_RETURN',ret.returnRef)
    l.returned+=qty;l.save()
    # Credit invoices reduce receivables before issuing a cash refund.
    due=max(ZERO,inv.total-inv.paid-(SalesReturn.objects.filter(line__invoice=inv).exclude(pk=ret.pk).aggregate(n=Sum('refundAmount'))['n'] or ZERO))
    cash_refund=max(ZERO,refund-due)
    ledger(user,cash_refund,ret.refundMethod,'Outflow',ret.returnRef,'Sales refund','sales_return',ret.pk)
    return ret

def adjust(user,data,wastage=False):
    loc=location(user,data.get('location'))
    if data.get('itemId'):
        model=Material if data.get('itemType','Raw Material')=='Raw Material' else Variant
        item=owned(model,data['itemId'],user)
    else:
        item=Material.objects.filter(organization=user.organization,name=data.get('item')).first()
        if not item: item=Variant.objects.filter(organization=user.organization).filter(Q(sku=data.get('item'))|Q(name=data.get('item'))).first()
        if not item: raise ValidationError('Select an existing material name or finished SKU.')
    qty=D(data.get('qty') if wastage else data.get('quantity'),True)
    reason=data.get('reason','').strip()
    if not reason: raise ValidationError('A reason is required.')
    sign=-1 if wastage or data.get('adjustmentType')=='subtract' else 1
    if not wastage and data.get('adjustmentType') not in ['add','subtract','remove']: raise ValidationError('Use add or subtract adjustment type.')
    if data.get('adjustmentType')=='remove': sign=-1
    s=post_stock(user,loc,item,qty*sign,'WASTAGE' if wastage else 'STOCK_ADJUSTMENT',number('WST' if wastage else 'ADJ',user.organization),reason)
    if wastage:
        return Wastage.objects.create(organization=user.organization,date=data.get('date') or date.today(),stock=s,wastageType=data.get('wastageType','Damage'),qty=qty,cost=cash(qty*(item.currentCost if isinstance(item,Material) else item.costPrice)),relatedBatch=data.get('relatedBatch',''),reason=reason,user=user)
    return s.movements.latest('date')


def bill_credit(bill):
    """Allocate supplier debit notes in a stable bill creation order per received PO.

    A credit reduces the payable, never pretends to be a cash payment.
    Excess credit on a fully paid bill remains a supplier credit, not a refund.
    """
    ref=bill.linkedRef.split(' / ')[0]
    receipt=Receipt.objects.filter(organization=bill.organization,grnNumber=ref).first()
    if receipt: ref=receipt.order.poNumber
    credit=PurchaseReturn.objects.filter(organization=bill.organization,supplier=bill.supplier,linkedRef=ref).aggregate(n=Sum('totalAmount'))['n'] or ZERO
    if not credit: return ZERO
    bills=Bill.objects.filter(organization=bill.organization,supplier=bill.supplier).order_by('created_at','pk')
    for earlier in bills:
        earlier_ref=earlier.linkedRef.split(' / ')[0]
        grn=Receipt.objects.filter(organization=bill.organization,grnNumber=earlier_ref).first()
        if grn: earlier_ref=grn.order.poNumber
        if earlier_ref!=ref: continue
        allocated=min(credit,earlier.amount)
        if earlier.pk==bill.pk: return allocated
        credit-=allocated
    return ZERO

def recipe_lines(v):
    if not v.formulaId.percentageRecipe: return list(v.formulaId.lines.select_related('material').order_by('material_id'))
    from types import SimpleNamespace
    rows=[SimpleNamespace(material=l.material,material_id=l.material_id,qty=(v.fillVolumeMl*l.percentage/100).quantize(Decimal('.0001'))) for l in v.formulaId.percentages.select_related('material').order_by('material_id')]
    rows += [SimpleNamespace(material=l.material,material_id=l.material_id,qty=l.qty) for l in v.packaging.select_related('material').order_by('material_id')]
    return rows
