from datetime import date
from decimal import Decimal
from django.db import transaction
from django.db.models import Q, Sum
from rest_framework import viewsets, serializers, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from drf_spectacular.utils import extend_schema
from apps.accounts.permissions import BusinessPermission, has
from . import models as m, serializers as s, services as svc

class InputSerializer(serializers.Serializer):
    code=serializers.CharField(required=False)
    name=serializers.CharField(required=False)
    version=serializers.CharField(required=False)
    status=serializers.CharField(required=False)
    percentageRecipe=serializers.BooleanField(required=False)
    percentageIngredients=serializers.ListField(child=serializers.DictField(),required=False)
    formulaId=serializers.CharField(required=False)
    variants=serializers.ListField(child=serializers.DictField(),required=False)
    requestKey=serializers.CharField(required=False)
    sourceWarehouseId=serializers.CharField(required=False)
    finishedWarehouseId=serializers.CharField(required=False)
    fragranceId=serializers.CharField(required=False)
    concentrationId=serializers.CharField(required=False)
    bottleSizeId=serializers.CharField(required=False)
    laborCost=serializers.DecimalField(max_digits=18,decimal_places=4,required=False,min_value=0)
    cleaningAllocation=serializers.DecimalField(max_digits=18,decimal_places=4,required=False,min_value=0)
    otherCost=serializers.DecimalField(max_digits=18,decimal_places=4,required=False,min_value=0)
    packaging=serializers.ListField(child=serializers.DictField(),required=False)
    productVariantId=serializers.CharField(required=False)
    variantId=serializers.CharField(required=False)
    warehouseId=serializers.CharField(required=False)
    warehouseName=serializers.CharField(required=False)
    branchId=serializers.CharField(required=False)
    customerId=serializers.CharField(required=False)
    supplierName=serializers.CharField(required=False)
    sourceType=serializers.CharField(required=False)
    sourceName=serializers.CharField(required=False)
    destType=serializers.CharField(required=False)
    destName=serializers.CharField(required=False)
    location=serializers.CharField(required=False)
    item=serializers.CharField(required=False)
    itemId=serializers.CharField(required=False)
    itemType=serializers.CharField(required=False)
    adjustmentType=serializers.ChoiceField(choices=['add','subtract'],required=False)
    quantity=serializers.DecimalField(max_digits=18,decimal_places=4,required=False)
    plannedQty=serializers.IntegerField(required=False,min_value=1)
    actualProduced=serializers.IntegerField(required=False,min_value=1)
    qty=serializers.DecimalField(max_digits=18,decimal_places=4,required=False)
    amount=serializers.DecimalField(max_digits=18,decimal_places=4,required=False)
    discount=serializers.DecimalField(max_digits=18,decimal_places=4,required=False)
    date=serializers.DateField(required=False)
    orderDate=serializers.DateField(required=False)
    expectedDate=serializers.DateField(required=False)
    receiveDate=serializers.DateField(required=False)
    notes=serializers.CharField(required=False)
    reason=serializers.CharField(required=False)
    condition=serializers.CharField(required=False)
    invoiceNumber=serializers.CharField(required=False)
    sku=serializers.CharField(required=False)
    poNumber=serializers.CharField(required=False)
    deliveryNoteNo=serializers.CharField(required=False)
    linkedRef=serializers.CharField(required=False)
    material=serializers.CharField(required=False)
    billId=serializers.CharField(required=False)
    paymentMethod=serializers.CharField(required=False)
    refundMethod=serializers.CharField(required=False)
    method=serializers.CharField(required=False)
    items=serializers.ListField(child=serializers.DictField(),required=False)
    cart=serializers.ListField(child=serializers.DictField(),required=False)
    actualConsumption=serializers.ListField(child=serializers.DictField(),required=False)
    """Workflow inputs are validated in posting services, including nested quantities."""
    def to_internal_value(self,data):
        if not isinstance(data,dict): raise ValidationError('Expected an object.')
        data=dict(data)
        for k in ['date','orderDate','expectedDate','receiveDate','dueDate','effectiveDate']:
            if k in data and data[k]: data[k]=serializers.DateField().run_validation(data[k])
        for k in ['items','cart','actualConsumption','packaging']:
            if k in data and (not isinstance(data[k],list) or any(not isinstance(v,dict) for v in data[k])): raise ValidationError({k:'Expected an array of objects.'})
        return data

class TenantViewSet(viewsets.ModelViewSet):
    permission_classes=[BusinessPermission]
    read_permissions=['inventory.view'];write_permissions=['*'];action_permissions={}
    pagination_class=None
    def get_queryset(self):
        from apps.accounts.access import scoped_erp
        qs=scoped_erp(self.queryset.filter(organization_id=self.request.user.organization_id),self.request.user).order_by('-created_at')
        search=self.request.query_params.get('search')
        if search:
            fields=[f.name for f in qs.model._meta.fields if isinstance(f,(m.models.CharField,m.models.TextField)) and f.name!='id']
            q=Q()
            for f in fields: q|=Q(**{f+'__icontains':search})
            qs=qs.filter(q)
        for key in ['status','category','productId','fragranceId','concentrationId','bottleSizeId','formulaId']:
            if key in self.request.query_params and key in [f.name for f in qs.model._meta.fields]: qs=qs.filter(**{key:self.request.query_params[key]})
        return qs
    def list(self,request,*args,**kwargs):
        # Arrays match the existing UI; pagination is opt-in for API consumers.
        if 'page' not in request.query_params: return super().list(request,*args,**kwargs)
        from rest_framework.pagination import PageNumberPagination
        paginator=PageNumberPagination();paginator.page_size=50;paginator.page_size_query_param='page_size';paginator.max_page_size=200
        items=paginator.paginate_queryset(self.filter_queryset(self.get_queryset()),request)
        return paginator.get_paginated_response(self.get_serializer(items,many=True).data)
    def perform_create(self,serializer): serializer.save(organization=self.request.user.organization)
    @transaction.atomic
    def create(self,*args,**kwargs): return super().create(*args,**kwargs)
    @transaction.atomic
    def update(self,*args,**kwargs): return super().update(*args,**kwargs)
    @transaction.atomic
    def destroy(self,*args,**kwargs): return super().destroy(*args,**kwargs)
    @transaction.atomic
    def dispatch(self,*args,**kwargs):return super().dispatch(*args,**kwargs)
    def initial(self,request,*args,**kwargs):
        super().initial(request,*args,**kwargs)
        if request.method in ['POST','PUT','PATCH','DELETE'] and transaction.get_connection().in_atomic_block:
            from apps.accounts.models import Organization
            Organization.objects.select_for_update().get(pk=request.user.organization_id)
    def validated_input(self):
        inp=InputSerializer(data=self.request.data);inp.is_valid(raise_exception=True);return inp.validated_data
    def output(self,obj,code=200): return Response(svc.json_num(self.get_serializer(obj).data),status=code)

class LocationViewSet(TenantViewSet):
    queryset=m.Location.objects.all();serializer_class=s.LocationSerializer
    read_permissions=['warehouse.view','branch.view','inventory.view','production.view','sales.pos','transfers.view','purchases.view','purchases.bills','reports.branch','reports.finance','finance.view'];write_permissions=['warehouse.manage']
    kind='Warehouse'
    def get_queryset(self):
        qs=super().get_queryset().filter(kind=self.kind)
        # Location catalogs can be seen for transfers; stock quantities remain scoped.
        return qs
    def get_object(self):
        if self.action in ['destroy','update','partial_update']:
            from django.shortcuts import get_object_or_404
            obj=get_object_or_404(m.Location,organization=self.request.user.organization,kind=self.kind,pk=self.kwargs['pk'])
            svc.enforce_location(self.request.user,obj);return obj
        return super().get_object()
    def perform_create(self,serializer):
        if self.request.user.organization.singleLocationMode:raise ValidationError('Single-location mode already has its default branch and warehouse.')
        serializer.save(organization=self.request.user.organization,kind=self.kind)
    def perform_update(self,serializer):
        if self.request.user.organization.singleLocationMode and (serializer.validated_data.get('isVirtual') or serializer.validated_data.get('status')=='inactive'):raise ValidationError('Default locations must remain active and physical.')
        svc.enforce_location(self.request.user,serializer.instance);serializer.save()
    def perform_destroy(self,instance):
        if self.request.user.organization.singleLocationMode:raise ValidationError('Default store locations cannot be deleted in single-location mode.')
        svc.enforce_location(self.request.user,instance);instance.delete()
    @action(detail=True,methods=['get'])
    def stock(self,request,pk=None):
        loc=self.get_object();svc.enforce_location(request.user,loc)
        return Response(svc.json_num({'rawMaterials':s.MaterialSerializer(m.Material.objects.filter(stock__location=loc),many=True,context=self.get_serializer_context()).data,'finishedProducts':s.VariantSerializer(m.Variant.objects.filter(stock__location=loc),many=True,context=self.get_serializer_context()).data,'movements':s.MovementSerializer(m.Movement.objects.filter(stock__location=loc),many=True,context=self.get_serializer_context()).data,'transfers':s.TransferSerializer(m.Transfer.objects.filter(Q(source=loc)|Q(destination=loc)),many=True,context=self.get_serializer_context()).data}))
class BranchViewSet(LocationViewSet): kind='Branch';write_permissions=['*']

class SupplierViewSet(TenantViewSet):
    queryset=m.Supplier.objects.all();serializer_class=s.SupplierSerializer
    read_permissions=['purchases.view','purchases.bills','finance.view'];write_permissions=['*']
    def perform_create(self,serializer): serializer.save(organization=self.request.user.organization,code='')
    def retrieve(self,request,*args,**kwargs):
        o=self.get_object();data=dict(self.get_serializer(o).data)
        data.update(purchaseOrders=s.PurchaseOrderSerializer(o.purchaseorder_set.all(),many=True).data,bills=s.BillSerializer(o.bill_set.all(),many=True).data,returns=s.PurchaseReturnSerializer(o.purchasereturn_set.all(),many=True).data,payments=[{'id':p.pk,'date':p.date,'amount':p.amount,'method':p.method,'reference':p.reference or p.bill.billNumber} for p in m.SupplierPayment.objects.filter(bill__supplier=o)])
        return Response(svc.json_num(data))
class CustomerViewSet(TenantViewSet):
    action_permissions={'update':['customers.manage'],'partial_update':['customers.manage'],'destroy':['customers.manage']}

    queryset=m.Customer.objects.all();serializer_class=s.CustomerSerializer
    read_permissions=['sales.view','sales.pos','customers.manage','finance.view'];write_permissions=['customers.manage','customers.quick_add']
    def retrieve(self,request,*args,**kwargs):
        o=self.get_object();data=dict(self.get_serializer(o).data)
        inv=o.invoice_set.all()
        from apps.accounts.access import scoped_erp
        inv=scoped_erp(inv,request.user)
        data.update(invoices=s.InvoiceSerializer(inv,many=True).data,returns=s.SalesReturnSerializer(m.SalesReturn.objects.filter(line__invoice__in=inv),many=True).data,payments=[{'id':i.pk,'date':i.date,'invoiceNumber':i.invoiceNumber,'amount':i.paid,'method':i.paymentMethod,'status':i.status} for i in inv])
        return Response(svc.json_num(data))
class MaterialCategoryViewSet(TenantViewSet):
    queryset=m.MaterialCategory.objects.all();serializer_class=s.MaterialCategorySerializer
    read_permissions=['inventory.view','production.view','production.formulation','purchases.view','purchases.bills','transfers.view'];write_permissions=['*','warehouse.manage']
    def perform_update(self,serializer):
        obj=serializer.save()
        obj.materials.update(category=obj.name)

class MaterialViewSet(TenantViewSet):
    def perform_destroy(self,instance):
        for product in m.Product.objects.filter(organization=instance.organization,directBlend=True).only('recipe','packagingRecipe'):
            if any(row.get('materialId')==instance.pk for row in product.recipe+product.packagingRecipe):raise ValidationError('Material is used in a product recipe/packaging set. Set it inactive instead.')
        super().perform_destroy(instance)
    queryset=m.Material.objects.all();serializer_class=s.MaterialSerializer
    read_permissions=['inventory.view','production.view','production.formulation','transfers.view','purchases.view','purchases.bills'];write_permissions=['*','warehouse.manage']
    def perform_create(self,serializer):
        serializer.save(organization=self.request.user.organization)
class FragranceViewSet(TenantViewSet):
    def perform_destroy(self,instance):
        if isinstance(instance,m.Fragrance):
            for product in m.Product.objects.filter(organization=instance.organization,directBlend=True).only('recipe'):
                if any(row.get('fragranceId')==instance.pk for row in product.recipe):raise ValidationError('Fragrance is used in a product formulation. Set it inactive instead.')
        super().perform_destroy(instance)
    queryset=m.Fragrance.objects.all();serializer_class=s.FragranceSerializer
    read_permissions=['production.view','production.formulation','inventory.view','sales.pos'];write_permissions=['production.formulation']
class ConcentrationViewSet(FragranceViewSet): queryset=m.Concentration.objects.all();serializer_class=s.ConcentrationSerializer
class BottleSizeViewSet(FragranceViewSet): queryset=m.BottleSize.objects.all();serializer_class=s.BottleSizeSerializer
class ProductViewSet(TenantViewSet):
    @transaction.atomic
    def destroy(self,request,*args,**kwargs):
        product=self.get_object()
        if isinstance(product,m.Product) and product.saleLines.exists():raise ValidationError('Product sales history is protected. Set this product inactive instead.')
        variants=[product] if isinstance(product,m.Variant) else list(product.variants.all())
        for v in variants:
            if m.Stock.objects.filter(variant=v).exists() or m.Batch.objects.filter(variant=v).exists() or m.InvoiceLine.objects.filter(variant=v).exists() or m.TransferLine.objects.filter(variant=v).exists(): raise ValidationError('Product inventory or transaction history is protected. Set the product/variant inactive instead.')
        for v in variants: v.packaging.all().delete();v.delete()
        if not isinstance(product,m.Variant): product.delete()
        return Response(status=204)

    @extend_schema(request=InputSerializer,responses=dict,operation_id="product_unified_create")
    @action(detail=False,methods=["post"],url_path="unified")
    @transaction.atomic
    def unified(self,request):
        from .workflow import save_product
        data={**request.data,'code':''};data['variants']=[{**v,'sku':''} if not v.get('id') else v for v in data.get('variants',[])]
        product=save_product(request.user,data)
        return self.output(product,201)
    @extend_schema(request=InputSerializer,responses=dict,operation_id="product_unified_update")
    @action(detail=True,methods=["post"],url_path="unified")
    @transaction.atomic
    def unified_update(self,request,pk=None):
        from .workflow import save_product
        data={**request.data};data['variants']=[{**v,'sku':''} if not v.get('id') else v for v in data.get('variants',[])]
        return self.output(save_product(request.user,data,self.get_object()))
    @action(detail=True,methods=["get"])
    @extend_schema(responses=dict)
    def workspace(self,request,pk=None):
        from .workflow import workspace
        return Response(svc.json_num(workspace(request.user,self.get_object(),self.get_serializer_context())))
    @action(detail=True,methods=["post"],permission_classes=[BusinessPermission])
    @transaction.atomic
    @extend_schema(request=InputSerializer,responses=dict)
    def manufacture(self,request,pk=None):
        from .workflow import manufacture
        batch=manufacture(request.user,self.get_object(),request.data)
        return Response(svc.json_num(s.BatchSerializer(batch,context=self.get_serializer_context()).data))
    action_permissions={"manufacture":["production.add_batch"]}
    queryset=m.Product.objects.all();serializer_class=s.ProductSerializer
    read_permissions=['inventory.view','sales.pos','sales.view','production.view','transfers.view'];write_permissions=['*']
    def perform_create(self,serializer): serializer.save(organization=self.request.user.organization,code='')
class VariantViewSet(TenantViewSet):
    read_permissions=ProductViewSet.read_permissions
    write_permissions=ProductViewSet.write_permissions
    def destroy(self,request,*args,**kwargs): return ProductViewSet.destroy(self,request,*args,**kwargs)
    queryset=m.Variant.objects.all();serializer_class=s.VariantSerializer
    def perform_create(self,serializer):
        data=serializer.validated_data;f=data['formulaId'];name=f"{data['productId'].name} {data['bottleSizeId'].name} {data['concentrationId'].code}"
        serializer.save(organization=self.request.user.organization,name=name,costPrice=f.estimatedUnitCost)
    @action(detail=True,methods=['post'])
    @transaction.atomic
    def pricing(self,request,pk=None):
        v=self.get_object();data=request.data
        price=svc.D(data.get('sellingPrice',v.sellingPrice));minimum=svc.D(data.get('minSellingPrice',v.minSellingPrice))
        if minimum>price: raise ValidationError('Minimum selling price exceeds selling price.')
        v.sellingPrice=price;v.minSellingPrice=minimum;v.mrp=svc.D(data.get('mrp',v.mrp));v.save(update_fields=['sellingPrice','minSellingPrice','mrp'])
        return self.output(v)
    @action(detail=True,methods=['get'])
    def costing(self,request,pk=None):
        v=self.get_object();f=v.formulaId
        if f.percentageRecipe:
            from .workflow import costing
            return Response(svc.json_num(costing(v)))
        return Response(svc.json_num({'liquidCost':sum(l.qty*l.rate for l in f.lines.filter(group='ingredients')),'packagingCost':sum(l.qty*l.rate for l in f.lines.filter(group='packaging')),'manufacturingCost':f.laborCost+f.cleaningAllocation+f.otherCost,'costPrice':f.estimatedUnitCost,'inventoryUnitCost':v.costPrice,'formula':s.FormulaSerializer(f).data}))
class FormulaViewSet(TenantViewSet):
    @transaction.atomic
    def destroy(self,request,*args,**kwargs):
        formula=m.Formula.objects.select_for_update().get(pk=self.get_object().pk)
        if m.Batch.objects.filter(formula=formula).exists() or m.Variant.objects.filter(formulaId=formula).exists():
            from django.db.models.deletion import ProtectedError
            raise ProtectedError('The formulation is referenced by production or a variant.',[formula])
        formula.lines.all().delete();formula.percentages.all().delete();formula.delete()
        return Response(status=204)

    queryset=m.Formula.objects.all();serializer_class=s.FormulaSerializer
    read_permissions=['production.view','production.formulation','inventory.view'];write_permissions=['production.formulation']
    @extend_schema(request=InputSerializer)
    @transaction.atomic
    def create(self,request,*args,**kwargs):
        data={**self.validated_input(),'code':''}
        return self.output(svc.save_formula(request.user,data),201)
    @extend_schema(request=InputSerializer)
    @transaction.atomic
    def update(self,request,*args,**kwargs):
        obj=self.get_object();data={**self.validated_input(),'code':obj.code}
        return self.output(svc.save_formula(request.user,data,obj))
    @extend_schema(request=InputSerializer,responses=dict)
    @action(detail=False,methods=['post'])
    def preview(self,request): return Response(svc.json_num(svc.formula_preview(request.user,self.validated_input())))

class PostedViewSet(TenantViewSet):
    def update(self,*args,**kwargs): raise ValidationError('Posted business records are immutable. Use a return or reversal.')
    def destroy(self,*args,**kwargs): raise ValidationError('Posted business records cannot be deleted. Use a return or reversal.')
class BatchViewSet(PostedViewSet):
    queryset=m.Batch.objects.all();serializer_class=s.BatchSerializer
    read_permissions=['production.view'];write_permissions=['production.add_batch'];action_permissions={'complete':['production.complete'],'wastage':['production.wastage','inventory.wastage']}
    def get_queryset(self):
        qs=super().get_queryset()
        return qs
    @extend_schema(request=InputSerializer)
    @transaction.atomic
    def create(self,request,*args,**kwargs): return self.output(svc.create_batch(request.user,self.validated_input()),201)
    @transaction.atomic
    def update(self,request,*args,**kwargs):
        b=m.Batch.objects.select_for_update().get(pk=self.get_object().pk)
        if b.status!='Draft': raise ValidationError('Only Draft batches can be edited.')
        svc.enforce_location(request.user,b.warehouse)
        data=self.validated_input();qty=svc.integer(data.get('plannedQty',b.plannedQty));ratio=Decimal(qty)/b.plannedQty
        for l in b.consumptions.all(): l.standard*=ratio;l.actual=l.standard;l.save()
        loc=svc.location(request.user,data.get('warehouseName') or b.warehouse.name,'Warehouse');b.warehouse=loc
        b.overheadCost*=ratio;b.plannedQty=qty;b.totalCost=b.unitCost*qty;b.notes=data.get('notes',b.notes);b.date=data.get('date',b.date);b.save()
        return self.output(b)
    def destroy(self,request,*args,**kwargs):
        b=self.get_object()
        if b.status!='Draft': return super().destroy(request,*args,**kwargs)
        b.consumptions.all().delete();b.delete();return Response(status=204)
    @extend_schema(request=InputSerializer)
    @action(detail=True,methods=['post'])
    @transaction.atomic
    def complete(self,request,pk=None):
        b=m.Batch.objects.select_for_update().get(pk=self.get_object().pk)
        return self.output(svc.complete_batch(request.user,b,self.validated_input()))
    @extend_schema(request=InputSerializer,responses=s.WastageSerializer)
    @action(detail=True,methods=['post'])
    @transaction.atomic
    def wastage(self,request,pk=None):
        b=self.get_object();data=self.validated_input();data.update(location=b.warehouse.name,relatedBatch=b.batchNo)
        o=svc.adjust(request.user,data,True);return Response(svc.json_num(s.WastageSerializer(o).data),status=201)
class TransferViewSet(PostedViewSet):
    @transaction.atomic
    def update(self,request,*args,**kwargs):
        current=m.Transfer.objects.select_for_update().get(pk=self.get_object().pk)
        svc.enforce_location(request.user,current.source)
        if current.status!='Requested': raise ValidationError('Only requested transfers can be edited.')
        # Validate replacement through the same complete create workflow before touching the draft.
        payload=dict(s.TransferSerializer(current,context=self.get_serializer_context()).data)
        payload.update(self.validated_input())
        replacement=svc.transfer_create(request.user,payload)
        current.lines.all().delete()
        replacement.lines.update(transfer=current)
        current.source=replacement.source;current.destination=replacement.destination
        current.date=replacement.date;current.notes=replacement.notes;current.save()
        replacement.delete()
        return self.output(current)

    queryset=m.Transfer.objects.all();serializer_class=s.TransferSerializer
    read_permissions=['transfers.view'];write_permissions=['transfers.create']
    action_permissions={'approve':['*'],'dispatch_transfer':['transfers.dispatch'],'receive':['transfers.receive'],'cancel':['transfers.create']}
    def get_queryset(self):
        qs=super().get_queryset()
        return qs
    @extend_schema(request=InputSerializer)
    @transaction.atomic
    def create(self,request,*args,**kwargs): return self.output(svc.transfer_create(request.user,self.validated_input()),201)
    def run(self,name):
        with transaction.atomic():
            t=m.Transfer.objects.select_for_update().get(pk=self.get_object().pk)
            return self.output(svc.transfer_action(self.request.user,t,name,self.validated_input()))
    @action(detail=True,methods=['post'])
    def approve(self,request,pk=None): return self.run('approve')
    @action(detail=True,methods=['post'],url_path='dispatch')
    def dispatch_transfer(self,request,pk=None): return self.run('dispatch')
    @extend_schema(request=InputSerializer)
    @action(detail=True,methods=['post'])
    def receive(self,request,pk=None): return self.run('receive')
    @action(detail=True,methods=['post'])
    def cancel(self,request,pk=None): return self.run('cancel')
class PurchaseOrderViewSet(PostedViewSet):
    queryset=m.PurchaseOrder.objects.all();serializer_class=s.PurchaseOrderSerializer
    read_permissions=['purchases.view','purchases.bills'];write_permissions=['*']
    def get_queryset(self):
        qs=super().get_queryset()
        return qs
    @extend_schema(request=InputSerializer)
    @transaction.atomic
    def create(self,request,*args,**kwargs): return self.output(svc.create_po(request.user,self.validated_input()),201)
    @transaction.atomic
    def update(self,request,*args,**kwargs):
        old=m.PurchaseOrder.objects.select_for_update().get(pk=self.get_object().pk)
        if old.receipt_set.exists() or m.Bill.objects.filter(organization=old.organization,linkedRef__startswith=old.poNumber).exists(): raise ValidationError('An order with receipts or bills cannot be changed.')
        data=self.validated_input()
        new=svc.create_po(request.user,data)
        for field in ['supplier','warehouse','orderDate','expectedDate','notes','subtotal','discountTotal','taxTotal','grandTotal']: setattr(old,field,getattr(new,field))
        old.lines.all().delete()
        new.lines.update(order=old);new.delete();old.save();return self.output(old)
    @transaction.atomic
    def destroy(self,request,*args,**kwargs):
        old=self.get_object()
        if old.receipt_set.exists() or m.Bill.objects.filter(organization=old.organization,linkedRef__startswith=old.poNumber).exists(): return super().destroy(request,*args,**kwargs)
        old.lines.all().delete();old.delete();return Response(status=204)
class ReceiptViewSet(PurchaseOrderViewSet):
    update=PostedViewSet.update
    destroy=PostedViewSet.destroy
    queryset=m.Receipt.objects.all();serializer_class=s.ReceiptSerializer;write_permissions=['purchases.grn']
    def get_queryset(self):
        qs=TenantViewSet.get_queryset(self)
        return qs
    @extend_schema(request=InputSerializer)
    @transaction.atomic
    def create(self,request,*args,**kwargs): return self.output(svc.create_grn(request.user,self.validated_input()),201)
class PurchaseReturnViewSet(PurchaseOrderViewSet):
    destroy=PostedViewSet.destroy
    queryset=m.PurchaseReturn.objects.all();serializer_class=s.PurchaseReturnSerializer;write_permissions=['purchases.returns']
    @extend_schema(request=InputSerializer)
    @transaction.atomic
    def create(self,request,*args,**kwargs): return self.output(svc.create_purchase_return(request.user,self.validated_input()),201)
    @transaction.atomic
    def update(self,request,*args,**kwargs):
        o=self.get_object()
        if set(request.data)!= {'reason'} or not request.data['reason'].strip(): raise ValidationError('Only the return reason may be corrected after posting.')
        o.reason=request.data['reason'];o.save();return self.output(o)
class BillViewSet(PostedViewSet):
    queryset=m.Bill.objects.all();serializer_class=s.BillSerializer
    read_permissions=['purchases.view','purchases.bills','finance.payables'];write_permissions=['purchases.bills']
    @transaction.atomic
    def create(self,request,*args,**kwargs):
        data=dict(request.data);sup=svc.owned(m.Supplier,data.get('supplierName'),request.user,'name');data['supplier']=sup.pk
        ser=self.get_serializer(data=data);ser.is_valid(raise_exception=True);bill=ser.save(organization=request.user.organization)
        if not m.PurchaseOrder.objects.filter(organization=request.user.organization,supplier=sup,poNumber=bill.linkedRef.split(' / ')[0]).exists(): raise ValidationError('Linked reference must start with a purchase order belonging to this supplier.')
        svc.ledger(request.user,bill.paid,'Bank','Outflow',bill.billNumber,'Initial vendor payment','bill',bill.pk,bill.date)
        return self.output(bill,201)
class InvoiceViewSet(PostedViewSet):
    queryset=m.Invoice.objects.all();serializer_class=s.InvoiceSerializer
    read_permissions=['sales.view','finance.view'];write_permissions=['sales.pos']
    def get_queryset(self):
        qs=super().get_queryset()
        return qs
    def create(self,*args,**kwargs): raise ValidationError('Use /sales/pos/checkout/ to create an invoice.')
    @transaction.atomic
    def update(self,request,*args,**kwargs):
        obj=self.get_object()
        for field in ['total','subtotal','discount','tax','paid']:
            if field in request.data and svc.D(request.data[field])!=getattr(obj,field): raise ValidationError('Posted invoice amounts cannot be edited. Use a sales return.')
        for field in ['customerName','customerMobile']:
            if field in request.data: setattr(obj,field,str(request.data[field]).strip())
        if not obj.customerName: raise ValidationError('Customer name is required.')
        obj.full_clean();obj.save();return self.output(obj)
class SalesReturnViewSet(InvoiceViewSet):
    update=PostedViewSet.update
    queryset=m.SalesReturn.objects.all();serializer_class=s.SalesReturnSerializer;write_permissions=['sales.returns']
    def get_queryset(self):
        qs=TenantViewSet.get_queryset(self)
        return qs
    @extend_schema(request=InputSerializer)
    @transaction.atomic
    def create(self,request,*args,**kwargs): return self.output(svc.sales_return(request.user,self.validated_input()),201)
class WastageViewSet(PostedViewSet):
    queryset=m.Wastage.objects.all();serializer_class=s.WastageSerializer
    read_permissions=['inventory.view','production.view'];write_permissions=['inventory.wastage','production.wastage']
    def get_queryset(self): return super().get_queryset().filter(stock__in=svc.scoped_stocks(self.request.user))
    @extend_schema(request=InputSerializer)
    @transaction.atomic
    def create(self,request,*args,**kwargs):
        return self.output(svc.adjust(request.user,self.validated_input(),True),201)
    @transaction.atomic
    def update(self,request,*args,**kwargs):
        o=self.get_object()
        if set(request.data)!={'reason'} or not request.data['reason'].strip(): raise ValidationError('Only the reason may be corrected after posting wastage.')
        o.reason=request.data['reason'];o.save();return self.output(o)
class MovementViewSet(PostedViewSet):
    queryset=m.Movement.objects.all();serializer_class=s.MovementSerializer
    read_permissions=['inventory.view','production.view'];write_permissions=['inventory.adjust','branch.manage_stock']
    def get_queryset(self): return super().get_queryset().filter(stock__in=svc.scoped_stocks(self.request.user))
    def create(self,*args,**kwargs): raise ValidationError('Use inventory/adjustments/ to post a stock movement.')
class AdjustmentViewSet(MovementViewSet):
    def get_queryset(self): return super().get_queryset().filter(transaction='STOCK_ADJUSTMENT')
    @extend_schema(request=InputSerializer)
    @transaction.atomic
    def create(self,request,*args,**kwargs): return self.output(svc.adjust(request.user,self.validated_input()),201)
class ExpenseViewSet(TenantViewSet):
    queryset=m.Expense.objects.all();serializer_class=s.ExpenseSerializer
    read_permissions=['finance.view'];write_permissions=['finance.expenses']
    def perform_create(self,serializer):
        o=serializer.save(organization=self.request.user.organization,createdBy=self.request.user,location=self.request.data.get('location') or self.request.data.get('branchOrWarehouse',''))
        svc.ledger(self.request.user,o.amount,o.paymentMethod,'Outflow',o.reference or o.pk,o.description,'expense',o.pk,o.date)
    def perform_update(self,serializer):
        previous=serializer.instance
        if previous.reference.startswith('PAYROLL-'):raise ValidationError('Payroll expenses are controlled by HRMS.')
        svc.ledger(self.request.user,previous.amount,previous.paymentMethod,'Inflow',previous.reference or previous.pk,'Expense correction reversal','expense_reversal',previous.pk,previous.date)
        o=serializer.save()
        svc.ledger(self.request.user,o.amount,o.paymentMethod,'Outflow',o.reference or o.pk,o.description,'expense',o.pk,o.date)
    def perform_destroy(self,instance):
        if instance.reference.startswith('PAYROLL-'):raise ValidationError('Payroll expenses are controlled by HRMS.')
        svc.ledger(self.request.user,instance.amount,instance.paymentMethod,'Inflow',instance.reference or instance.pk,'Expense reversal','expense_reversal',instance.pk)
        instance.delete()
class LedgerViewSet(TenantViewSet):
    queryset=m.LedgerEntry.objects.all();serializer_class=s.LedgerSerializer
    read_permissions=['finance.view'];write_permissions=['finance.cash_bank']
    def perform_update(self,serializer):
        if set(self.request.data)-{'description'}: raise ValidationError('Posted ledger entries only allow description corrections; reverse and replace to correct amounts.')
        serializer.save()
    def perform_destroy(self,o):
        raise ValidationError('Posted entries cannot be deleted. Reverse a manual entry or correct its originating module.')
    @action(detail=True,methods=['post'])
    @transaction.atomic
    def reverse(self,request,pk=None):
        o=m.LedgerEntry.objects.select_for_update().get(pk=self.get_object().pk)
        if o.source!='manual' or o.status=='Reversed': raise ValidationError('Only unreversed manual entries can be reversed here.')
        svc.ledger(request.user,o.amount,o.account,'Outflow' if o.type=='Inflow' else 'Inflow',o.reference,'Reversal: '+o.description,'manual_reversal',o.pk)
        o.status='Reversed';o.save(update_fields=['status'])
        return self.output(o)
