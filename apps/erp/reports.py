"""Read projections derived entirely from posted records and location balances."""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from django.utils.timezone import localdate
from django.db.models import Sum
from . import models as m, services as svc, serializers as s
from .category_utils import material_type
from apps.accounts.permissions import has
from apps.accounts.access import scoped_erp,effective_permissions

def _recipe_minimums(user):
    """Minimum stock needed to make one unit of each configured direct-blend product.

    Keep the largest per-product requirement for each ingredient, not the sum:
    the alert indicates whether *any* product recipe is blocked by stock.
    """
    required = {}
    products = m.Product.objects.filter(organization=user.organization, directBlend=True)
    for product in products:
        try:
            volume = Decimal(str(product.fillVolumeMl))
        except (InvalidOperation, TypeError, ValueError):
            continue
        for row in product.recipe or []:
            try:
                material_id = str(row['materialId'])
                qty = volume * Decimal(str(row['percentage'])) / Decimal('100')
                if qty > 0:
                    required[material_id] = max(required.get(material_id, Decimal('0')), qty)
            except (KeyError, TypeError, InvalidOperation, ValueError):
                continue
        for row in product.packagingRecipe or []:
            try:
                material_id = str(row['materialId'])
                qty = Decimal(str(row['quantity']))
                if qty > 0:
                    required[material_id] = max(required.get(material_id, Decimal('0')), qty)
            except (KeyError, TypeError, InvalidOperation, ValueError):
                continue
    return required


def stock_rows(user):
    recipe_minimums = _recipe_minimums(user)
    rows=[]
    for stock in svc.scoped_stocks(user):
        item=stock.material or stock.variant
        cost=item.currentCost if stock.material_id else item.costPrice
        configured_min = item.minStock if stock.material_id or item.formulaId.percentageRecipe else 10
        recipe_min = recipe_minimums.get(str(item.pk), Decimal('0')) if stock.material_id else Decimal('0')
        threshold = max(configured_min, recipe_min)
        mov=stock.movements.all()
        incoming=sum(x.delta for x in mov if x.delta>0);outgoing=sum(-x.delta for x in mov if x.delta<0)
        rows.append({'id':stock.pk,'itemId':item.pk,'code':item.code if stock.material_id else item.sku,'name':item.name,'category':item.category if stock.material_id else item.concentrationId.code,'categoryType':material_type(item) if stock.material_id else '', 'itemType':'Raw Material' if stock.material_id else 'Finished Product','type':'Raw Material' if stock.material_id else 'Finished Goods','location':stock.location.name,'locationType':stock.location.kind,'opening':stock.quantity-incoming+outgoing,'incoming':incoming,'outgoing':outgoing,'available':stock.quantity,'stock':f'{stock.quantity} {item.unit if stock.material_id else "pcs"}','unit':item.unit if stock.material_id else 'pcs','unitCost':cost,'value':stock.quantity*cost,'totalValue':stock.quantity*cost,'minStock':threshold,'configuredMinStock':configured_min,'recipeMinStock':recipe_min,'stockStatus':'Out of Stock' if stock.quantity==0 else 'Low Stock' if stock.quantity<=threshold else 'Optimal'})
    return rows

def invoice_scope(user):
    qs=m.Invoice.objects.filter(organization=user.organization)
    from apps.accounts.access import scoped_erp
    qs=scoped_erp(qs,user)
    return qs

def build_report(user,filters):
    invoices=invoice_scope(user)
    from apps.accounts.access import scoped_erp
    expenses=scoped_erp(m.Expense.objects.filter(organization=user.organization),user)
    batches=scoped_erp(m.Batch.objects.filter(organization=user.organization,status='Completed'),user)
    permissions=effective_permissions(user)
    def allowed(*codes):return '*' in permissions or any(c in permissions for c in codes)
    if not allowed('sales.view','sales.invoice.view','reports.branch','reports.finance','reports.view'):invoices=invoices.none()
    if not allowed('finance.view','accounting.expense.view','reports.finance','reports.view'):expenses=expenses.none()
    if not allowed('production.view','inventory.product.view','inventory.batch.view','reports.finance','reports.view'):batches=batches.none()
    for key,lookup in [('fromDate','date__gte'),('toDate','date__lte')]:
        if filters.get(key):
            value=s.serializers.DateField().run_validation(filters[key])
            invoices=invoices.filter(**{lookup:value});expenses=expenses.filter(**{lookup:value});batches=batches.filter(**{lookup:value})
    branch=filters.get('branch','All Branches');warehouse=filters.get('warehouse','All Warehouses')
    if branch!='All Branches': invoices=invoices.filter(branch__name=branch);expenses=expenses.filter(location=branch)
    if warehouse!='All Warehouses': batches=batches.filter(warehouse__name=warehouse)
    products=defaultdict(lambda:{'qty':0,'revenue':svc.ZERO,'cogs':svc.ZERO})
    trend=defaultdict(lambda:{'sales':svc.ZERO,'profit':svc.ZERO})
    groups=defaultdict(lambda:{'qty':0,'revenue':svc.ZERO,'cogs':svc.ZERO})
    for l in m.InvoiceLine.objects.filter(invoice__in=invoices).select_related('invoice','variant__concentrationId'):
        refunds=m.SalesReturn.objects.filter(line=l).aggregate(n=Sum('refundAmount'))['n'] or svc.ZERO
        revenue=l.total-refunds;qty=l.qty-l.returned;cogs=(l.qty if l.product_id else qty)*l.costSnapshot
        p=products[l.sku];p.update(sku=l.sku,product=l.productName);p['qty']+=qty;p['revenue']+=revenue;p['cogs']+=cogs
        t=trend[str(l.invoice.date)];t['sales']+=revenue;t['profit']+=revenue-cogs
        g=groups['Custom blends' if l.product_id else l.variant.concentrationId.name];g['qty']+=qty;g['revenue']+=revenue;g['cogs']+=cogs
    performance=[]
    for p in products.values(): p.update(grossProfit=p['revenue']-p['cogs'],margin=f"{(p['revenue']-p['cogs'])/p['revenue']*100:.1f}%" if p['revenue'] else '0.0%');performance.append(p)
    gross=sum(p['revenue'] for p in performance);cogs=sum(p['cogs'] for p in performance);profit=gross-cogs;units=sum(p['qty'] for p in performance)
    exp=sum(e.amount for e in expenses)
    categories=defaultdict(lambda:svc.ZERO)
    for e in expenses:
        categories[e.category]+=e.amount
        for group in ['Rent','Courier','Marketing','Utilities']:
            if e.category.startswith(group) and e.category!=group: categories[group]+=e.amount
    rows=stock_rows(user) if allowed('inventory.view','inventory.stock.view','reports.branch','reports.finance','reports.view') else []
    if warehouse!='All Warehouses': rows=[r for r in rows if r['location']==warehouse]
    if branch!='All Branches': rows=[r for r in rows if r['location']==branch]
    raw=sum(r['value'] for r in rows if r['itemType']=='Raw Material');fin=sum(r['value'] for r in rows if r['itemType']=='Finished Product')
    pie=defaultdict(lambda:svc.ZERO)
    for r in rows: pie[r['category']]+=r['value']
    matrix=[]
    for name,g in groups.items():
        qty=g['qty'];revenue=g['revenue'];cost=g['cogs']
        matrix.append({'category':name,'avgSellingPrice':revenue/qty if qty else 0,'avgUnitCost':cost/qty if qty else 0,'grossProfitPerUnit':(revenue-cost)/qty if qty else 0,'margin':f'{(revenue-cost)/revenue*100:.1f}%' if revenue else '0.0%','categoryTotalRevenue':revenue})
    produced=sum(b.producedQty for b in batches)
    variance=sum((l.actual-l.standard)*l.rate for l in m.Consumption.objects.filter(batch__in=batches))
    cost_total=sum(b.totalCost for b in batches)
    return {'salesSummary':{'totalRevenue':gross,'unitsSold':units,'cogs':cogs,'grossProfit':profit,'grossMargin':f'{profit/gross*100:.1f}%' if gross else '0.0%','avgOrderValue':gross/invoices.count() if invoices.exists() else 0},'productPerformanceData':performance,'salesTrendData':[{'date':k,**v} for k,v in sorted(trend.items())],'inventorySummary':{'rawMaterialsValue':raw,'finishedGoodsValue':fin,'totalInventoryValue':raw+fin,'lowStockItemsCount':sum(r['stockStatus']!='Optimal' for r in rows)},'inventoryStockData':rows,'inventoryPieData':[{'name':k,'value':v} for k,v in pie.items()],'productionSummary':{'batchesExecuted':batches.count(),'finishedUnitsProduced':produced,'formulationVolume':f'{sum(b.producedQty*(b.variant.fillVolumeMl if b.variant.formulaId.percentageRecipe else b.variant.bottleSizeId.volumeMl) for b in batches.select_related("variant__bottleSizeId"))/1000} Liters','varianceRate':f'{variance/cost_total*100:.2f}%' if cost_total else '0.00%'},'productionBatchesData':[{'batchNo':b.batchNo,'product':b.variant.name,'warehouse':b.warehouse.name,'planned':b.plannedQty,'actual':b.producedQty,'unitCost':b.unitCost,'totalCost':b.totalCost,'variance':str(sum((l.actual-l.standard)*l.rate for l in b.consumptions.all())),'status':b.status} for b in batches.select_related('variant','warehouse')],'profitabilitySummary':{'grossMargin':f'{profit/gross*100:.1f}%' if gross else '0.0%','netProfitMargin':f'{(profit-exp)/gross*100:.1f}%' if gross else '0.0%','topProduct':max(performance,key=lambda p:p['grossProfit'])['product'] if performance else 'No sales','topChannel':branch if branch!='All Branches' else 'All Branches'},'profitabilityMatrix':matrix,'profitLoss':{'grossRevenue':gross,'cogsTotal':cogs,'grossProfitTotal':profit,'utilitiesExp':categories['Utilities'],'courierExp':categories['Courier'],'rentExp':categories['Rent'],'marketingExp':categories['Marketing'],'totalOperatingExpenses':exp,'netOperatingProfit':profit-exp}}

def cash_bank(user):
    entries=scoped_erp(m.LedgerEntry.objects.filter(organization=user.organization),user).order_by('-created_at')
    def account(name):
        qs=entries.filter(account=name);today=qs.filter(date=localdate())
        return {'accountName':name,'currentBalance':sum(e.amount if e.type=='Inflow' else -e.amount for e in qs),'todaysInflow':today.filter(type='Inflow').aggregate(n=Sum('amount'))['n'] or svc.ZERO,'todaysOutflow':today.filter(type='Outflow').aggregate(n=Sum('amount'))['n'] or svc.ZERO}
    return {'cashAccount':account('Cash'),'bankAccount':account('Bank'),'transactions':s.LedgerSerializer(entries,many=True).data}

def receivables(user):
    rows=[]
    for i in invoice_scope(user):
        outstanding=s.InvoiceSerializer(i).get_balance(i)
        if outstanding: rows.append({'id':i.pk,'customerName':i.customerName,'invoiceNumber':i.invoiceNumber,'invoiceDate':i.date,'total':i.total,'paid':i.paid,'outstanding':outstanding,'dueDate':i.date,'status':i.status})
    return rows

def payables(user):
    rows=[]
    for b in scoped_erp(m.Bill.objects.filter(organization=user.organization),user).select_related('supplier'):
        outstanding=s.BillSerializer(b).get_balance(b)
        if outstanding: rows.append({'id':b.pk,'supplierName':b.supplier.name,'billNumber':b.billNumber,'date':b.date,'total':b.amount,'paid':b.paid,'outstanding':outstanding,'dueDate':b.dueDate,'status':'Overdue' if b.dueDate<localdate() else 'Unpaid'})
    return rows
