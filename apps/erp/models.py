import uuid
from django.db import models
from django.db.models import Q
from django.core.validators import MinValueValidator, MaxValueValidator
from decimal import Decimal

def uid(): return uuid.uuid4().hex

def money(default=0): return models.DecimalField(max_digits=18,decimal_places=4,default=default,validators=[MinValueValidator(0)])
def relation(model,**kw): return models.ForeignKey(model,on_delete=models.PROTECT,**kw)

class TenantModel(models.Model):
    id=models.CharField(primary_key=True,max_length=40,default=uid,editable=False)
    organization=relation('accounts.Organization')
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta: abstract=True
    def save(self,*args,**kwargs):
        from apps.common.services.code_generator import generate_for,identifier_fields
        from django.db import transaction
        from rest_framework.exceptions import ValidationError
        with transaction.atomic():
            if self._state.adding:generate_for(self)
            else:
                fields=identifier_fields(type(self))
                if fields:
                    previous=type(self).objects.filter(pk=self.pk).values(*fields).first()
                    for field in fields:
                        if previous and previous[field] and previous[field]!=getattr(self,field):raise ValidationError({field:'Identifiers cannot be changed after creation.'})
            return super().save(*args,**kwargs)

class Master(TenantModel):
    name=models.CharField(max_length=160)
    status=models.CharField(max_length=20,choices=[('active','Active'),('inactive','Inactive')],default='active')
    class Meta: abstract=True
    def __str__(self): return self.name

class Location(Master):
    warehouse=relation("self",null=True,blank=True,related_name="linkedBranches",limit_choices_to={"kind":"Warehouse"})
    code=models.CharField(max_length=60)
    kind=models.CharField(max_length=20,choices=[('Warehouse','Warehouse'),('Branch','Branch')])
    location=models.CharField(max_length=240,blank=True)
    manager=models.CharField(max_length=120,blank=True)
    phone=models.CharField(max_length=40,blank=True)
    email=models.EmailField(blank=True)
    class Meta: constraints=[models.UniqueConstraint(fields=['organization','code'],name='location_code'),models.UniqueConstraint(fields=['organization','name'],name='location_name')]

class Supplier(Master):
    code=models.CharField(max_length=60)
    contactPerson=models.CharField(max_length=120,blank=True)
    phone=models.CharField(max_length=40,blank=True)
    mobile=models.CharField(max_length=40,blank=True)
    email=models.EmailField(blank=True)
    address=models.TextField(blank=True)
    taxId=models.CharField(max_length=80,blank=True)
    paymentTerms=models.CharField(max_length=80,blank=True)
    class Meta: constraints=[models.UniqueConstraint(fields=['organization','code'],name='supplier_code'),models.UniqueConstraint(fields=['organization','name'],name='supplier_name')]

class Customer(Master):
    mobile=models.CharField(max_length=40)
    email=models.EmailField(blank=True)
    address=models.TextField(blank=True)
    notes=models.TextField(blank=True)
    class Meta: constraints=[models.UniqueConstraint(fields=['organization','mobile'],name='customer_mobile')]

class MaterialCategory(Master):
    categoryType=models.CharField(max_length=20,choices=[('Perfume Oil','Perfume Oil'),('Solvent','Solvent'),('Packaging','Packaging'),('Other','Other')])
    unit=models.CharField(max_length=10,choices=[('ml','ml'),('pcs','pcs'),('g','g'),('kg','kg'),('L','L')])
    description=models.TextField(blank=True)
    class Meta: constraints=[models.UniqueConstraint(fields=['organization','name'],name='material_category_name')]

class Material(Master):
    compatibleBottleSizes=models.ManyToManyField("BottleSize",blank=True,related_name="compatibleMaterials")
    categoryRef=relation(MaterialCategory,null=True,blank=True,related_name='materials')
    code=models.CharField(max_length=60)
    category=models.CharField(max_length=160)
    unit=models.CharField(max_length=10,choices=[('ml','ml'),('pcs','pcs'),('g','g'),('kg','kg'),('L','L')],default='ml')
    currentCost=money()
    minStock=money()
    supplier=relation(Supplier,null=True,blank=True)
    description=models.TextField(blank=True)
    class Meta: constraints=[models.UniqueConstraint(fields=['organization','code'],name='material_code'),models.UniqueConstraint(fields=['organization','name'],name='material_name')]

class Fragrance(Master):
    notes=models.TextField(blank=True)
    code=models.CharField(max_length=60)
    refBrand=models.CharField(max_length=120,blank=True)
    category=models.CharField(max_length=60,blank=True)
    perfumeOilId=relation(Material)
    class Meta: constraints=[models.UniqueConstraint(fields=['organization','code'],name='fragrance_code')]

class Concentration(Master):
    description=models.TextField(blank=True)
    code=models.CharField(max_length=40)
    oilPercentage=models.DecimalField(max_digits=6,decimal_places=3,validators=[MinValueValidator(0),MaxValueValidator(100)])
    class Meta: constraints=[models.UniqueConstraint(fields=['organization','code'],name='concentration_code'),models.CheckConstraint(condition=Q(oilPercentage__gte=0,oilPercentage__lte=100),name='valid_oil_percentage')]

class BottleSize(Master):
    pumpMaterialRef=relation(Material,null=True,blank=True,related_name="pumpBottleSizes")
    capMaterialRef=relation(Material,null=True,blank=True,related_name="capBottleSizes")
    volumeMl=models.DecimalField(max_digits=10,decimal_places=3,validators=[MinValueValidator(Decimal('0.001'))])
    bottleMaterialRef=relation(Material)

class Formula(TenantModel):
    code=models.CharField(max_length=60,blank=True)
    name=models.CharField(max_length=160,blank=True)
    percentageRecipe=models.BooleanField(default=False)
    fragranceId=relation(Fragrance)
    concentrationId=relation(Concentration,null=True,blank=True)
    bottleSizeId=relation(BottleSize,null=True,blank=True)
    version=models.CharField(max_length=40,default='v1.0')
    status=models.CharField(max_length=20,default='active')
    effectiveDate=models.DateField(null=True,blank=True)
    oilQty=money()
    solventQty=money()
    laborCost=money()
    cleaningAllocation=money()
    otherCost=money()
    estimatedUnitCost=money()
    class Meta: constraints=[models.UniqueConstraint(fields=['organization','code','version'],condition=Q(percentageRecipe=True),name='percentage_formula_version')]

class FormulaLine(TenantModel):
    formula=relation(Formula,related_name='lines')
    material=relation(Material)
    group=models.CharField(max_length=20,choices=[('ingredients','Ingredients'),('packaging','Packaging')])
    qty=money()
    rate=money()
    required=models.BooleanField(default=True)
    class Meta: constraints=[models.UniqueConstraint(fields=['formula','material'],name='formula_material')]

class Product(Master):
    code=models.CharField(max_length=60)
    category=models.CharField(max_length=80,blank=True)
    description=models.TextField(blank=True)
    fragranceId=relation(Fragrance,null=True,blank=True)
    class Meta: constraints=[models.UniqueConstraint(fields=['organization','code'],name='product_code')]

class Variant(Master):
    plannedQuantity=models.PositiveIntegerField(default=1,validators=[MinValueValidator(1)])
    fillVolumeMl=money()
    additionalCost=money()
    minStock=money()
    productId=relation(Product,related_name='variants')
    fragranceId=relation(Fragrance)
    bottleSizeId=relation(BottleSize)
    concentrationId=relation(Concentration)
    formulaId=relation(Formula)
    sku=models.CharField(max_length=80)
    barcode=models.CharField(max_length=80,blank=True)
    costPrice=money()
    mrp=money()
    sellingPrice=money()
    minSellingPrice=money()
    class Meta: constraints=[models.UniqueConstraint(fields=['organization','sku'],name='variant_sku')]

class Stock(TenantModel):
    location=relation(Location)
    material=relation(Material,null=True,blank=True)
    variant=relation(Variant,null=True,blank=True)
    quantity=models.DecimalField(max_digits=18,decimal_places=4,default=0)
    class Meta:
        constraints=[models.CheckConstraint(condition=(Q(material__isnull=False,variant__isnull=True)|Q(material__isnull=True,variant__isnull=False)),name='stock_single_item'),models.CheckConstraint(condition=Q(quantity__gte=0),name='stock_nonnegative'),models.UniqueConstraint(fields=['location','material'],name='stock_material'),models.UniqueConstraint(fields=['location','variant'],name='stock_variant')]

class Movement(TenantModel):
    stock=relation(Stock,related_name='movements')
    date=models.DateTimeField(auto_now_add=True)
    transaction=models.CharField(max_length=60)
    reference=models.CharField(max_length=100)
    delta=models.DecimalField(max_digits=18,decimal_places=4)
    previousStock=money()
    newStock=money()
    reason=models.TextField(blank=True)
    user=relation('accounts.User')
    class Meta: indexes=[models.Index(fields=['organization','date'])]

class Batch(TenantModel):
    requestKey=models.CharField(max_length=64,blank=True)
    requestFingerprint=models.CharField(max_length=64,blank=True)
    branch=relation(Location,null=True,blank=True,related_name="production_branches")
    finishedWarehouse=relation(Location,null=True,blank=True,related_name="production_outputs")
    batchNo=models.CharField(max_length=80)
    variant=relation(Variant)
    warehouse=relation(Location)
    formula=relation(Formula)
    date=models.DateField()
    plannedQty=models.PositiveIntegerField()
    producedQty=models.PositiveIntegerField(default=0)
    status=models.CharField(max_length=20,default='Draft')
    unitCost=money()
    totalCost=money()
    overheadCost=money()
    notes=models.TextField(blank=True)
    class Meta: constraints=[models.UniqueConstraint(fields=['organization','requestKey'],condition=~Q(requestKey=''),name='batch_request_key'),models.UniqueConstraint(fields=['organization','batchNo'],name='batch_number'),models.CheckConstraint(condition=Q(plannedQty__gt=0),name='batch_positive')]

class Consumption(TenantModel):
    batch=relation(Batch,related_name='consumptions')
    material=relation(Material)
    standard=money()
    actual=money()
    rate=money()
    class Meta: constraints=[models.UniqueConstraint(fields=['batch','material'],name='batch_material')]

class Transfer(TenantModel):
    transferNo=models.CharField(max_length=80)
    source=relation(Location,related_name='outbound')
    destination=relation(Location,related_name='inbound')
    date=models.DateField()
    status=models.CharField(max_length=30,default='Requested')
    notes=models.TextField(blank=True)
    requestedBy=relation('accounts.User')
    approvedBy=relation('accounts.User',related_name='+',null=True,blank=True)
    dispatchedBy=relation('accounts.User',related_name='+',null=True,blank=True)
    receivedBy=relation('accounts.User',related_name='+',null=True,blank=True)
    approvedAt=models.DateTimeField(null=True,blank=True)
    dispatchedAt=models.DateTimeField(null=True,blank=True)
    receivedAt=models.DateTimeField(null=True,blank=True)
    class Meta: constraints=[models.UniqueConstraint(fields=['organization','transferNo'],name='transfer_number'),models.CheckConstraint(condition=~Q(source=models.F('destination')),name='different_transfer_locations')]

class TransferLine(TenantModel):
    transfer=relation(Transfer,related_name='lines')
    material=relation(Material,null=True,blank=True)
    variant=relation(Variant,null=True,blank=True)
    requestedQty=money()
    dispatchedQty=money()
    receivedQty=money()
    damagedQty=money()
    class Meta: constraints=[models.CheckConstraint(condition=(Q(material__isnull=False,variant__isnull=True)|Q(material__isnull=True,variant__isnull=False)),name='transfer_single_item')]

class PurchaseOrder(TenantModel):
    poNumber=models.CharField(max_length=80)
    supplier=relation(Supplier)
    warehouse=relation(Location)
    orderDate=models.DateField()
    expectedDate=models.DateField()
    status=models.CharField(max_length=30,default='Approved')
    notes=models.TextField(blank=True)
    subtotal=money()
    discountTotal=money()
    taxTotal=money()
    grandTotal=money()
    class Meta: constraints=[models.UniqueConstraint(fields=['organization','poNumber'],name='po_number')]

class PurchaseLine(TenantModel):
    order=relation(PurchaseOrder,related_name='lines')
    material=relation(Material)
    qty=money()
    rate=money()
    discount=money()
    tax=money()
    received=money()

class Receipt(TenantModel):
    grnNumber=models.CharField(max_length=80)
    order=relation(PurchaseOrder)
    receiveDate=models.DateField()
    deliveryNoteNo=models.CharField(max_length=100)
    status=models.CharField(max_length=30)
    class Meta: constraints=[models.UniqueConstraint(fields=['organization','deliveryNoteNo'],name='receipt_delivery_note')]

class ReceiptLine(TenantModel):
    receipt=relation(Receipt,related_name='lines')
    orderLine=relation(PurchaseLine)
    currentReceived=money()
    acceptedQty=money()
    rejectedQty=money()
    unitCost=money()

class Bill(TenantModel):
    supplierInvoiceNo=models.CharField(max_length=100,blank=True)
    billNumber=models.CharField(max_length=100)
    supplier=relation(Supplier)
    linkedRef=models.CharField(max_length=200)
    date=models.DateField()
    dueDate=models.DateField()
    amount=money()
    paid=money()
    class Meta: constraints=[models.UniqueConstraint(fields=['organization','billNumber'],name='bill_number'),models.CheckConstraint(condition=Q(paid__lte=models.F('amount')),name='bill_paid_limit')]

class SupplierPayment(TenantModel):
    bill=relation(Bill,related_name='payments')
    date=models.DateField()
    amount=money()
    method=models.CharField(max_length=40,default='Bank')
    reference=models.CharField(max_length=120,blank=True)

class PurchaseReturn(TenantModel):
    returnNumber=models.CharField(max_length=80)
    supplier=relation(Supplier)
    warehouse=relation(Location)
    material=relation(Material)
    linkedRef=models.CharField(max_length=200)
    date=models.DateField()
    qty=money()
    unitCost=money()
    totalAmount=money()
    reason=models.TextField()
    status=models.CharField(max_length=40,default='Debit Note Issued')

class Invoice(TenantModel):
    checkoutKey=models.CharField(max_length=64,blank=True,default='')
    checkoutFingerprint=models.CharField(max_length=64,blank=True,default='')

    invoiceNumber=models.CharField(max_length=80)
    branch=relation(Location)
    customer=relation(Customer,null=True,blank=True)
    customerName=models.CharField(max_length=160)
    customerMobile=models.CharField(max_length=40,blank=True)
    salesperson=relation('accounts.User')
    date=models.DateField()
    subtotal=money()
    discount=money()
    tax=money()
    total=money()
    paid=money()
    paymentMethod=models.CharField(max_length=40)
    status=models.CharField(max_length=30,default='Paid')
    class Meta: constraints=[models.UniqueConstraint(fields=['organization','invoiceNumber'],name='invoice_number'),models.UniqueConstraint(fields=['organization','checkoutKey'],condition=~Q(checkoutKey=''),name='invoice_checkout_key')];indexes=[models.Index(fields=['organization','date'])]

class InvoiceLine(TenantModel):
    invoice=relation(Invoice,related_name='lines')
    variant=relation(Variant)
    productName=models.CharField(max_length=160)
    sku=models.CharField(max_length=80)
    qty=models.PositiveIntegerField()
    rate=money()
    discount=money()
    total=money()
    costSnapshot=money()
    returned=models.PositiveIntegerField(default=0)
    class Meta: constraints=[models.CheckConstraint(condition=Q(returned__lte=models.F('qty')),name='return_limit')]

class SalesReturn(TenantModel):
    returnRef=models.CharField(max_length=80)
    line=relation(InvoiceLine)
    date=models.DateField()
    qty=models.PositiveIntegerField()
    condition=models.CharField(max_length=30)
    reason=models.TextField()
    refundMethod=models.CharField(max_length=30)
    refundAmount=money()

class Expense(TenantModel):
    createdBy=relation('accounts.User',related_name='+',null=True,blank=True)
    date=models.DateField()
    category=models.CharField(max_length=80)
    description=models.TextField()
    amount=money()
    paymentMethod=models.CharField(max_length=40,default='Cash')
    location=models.CharField(max_length=160,blank=True)
    reference=models.CharField(max_length=100,blank=True)
    status=models.CharField(max_length=30,default='Paid')

class Wastage(TenantModel):
    date=models.DateField()
    stock=relation(Stock)
    wastageType=models.CharField(max_length=80)
    qty=money()
    cost=money()
    relatedBatch=models.CharField(max_length=80,blank=True)
    reason=models.TextField()
    user=relation('accounts.User')

class LedgerEntry(TenantModel):
    date=models.DateField()
    account=models.CharField(max_length=40,choices=[('Cash','Cash'),('Bank','Bank')])
    type=models.CharField(max_length=20,choices=[('Inflow','Inflow'),('Outflow','Outflow')])
    reference=models.CharField(max_length=100)
    description=models.TextField()
    amount=money()
    source=models.CharField(max_length=40,default='manual')
    sourceId=models.CharField(max_length=40,blank=True)
    status=models.CharField(max_length=30,default='Posted')

class BalanceAdjustment(TenantModel):
    customer=relation(Customer,null=True,blank=True)
    supplier=relation(Supplier,null=True,blank=True)
    date=models.DateField()
    amount=models.DecimalField(max_digits=18,decimal_places=4)
    reason=models.TextField()
    class Meta: constraints=[models.CheckConstraint(condition=(Q(customer__isnull=False,supplier__isnull=True)|Q(customer__isnull=True,supplier__isnull=False)),name='balance_single_party')]

class PercentageIngredient(TenantModel):
    formula=relation(Formula,related_name='percentages')
    material=relation(Material)
    percentage=models.DecimalField(max_digits=7,decimal_places=4,validators=[MinValueValidator(Decimal('0.0001')),MaxValueValidator(100)])
    class Meta: constraints=[models.UniqueConstraint(fields=['formula','material'],name='percentage_material')]

class VariantPackaging(TenantModel):
    variant=relation(Variant,related_name='packaging')
    material=relation(Material)
    qty=money()
    class Meta: constraints=[models.UniqueConstraint(fields=['variant','material'],name='variant_packaging_material')]

class CodeSequence(TenantModel):
    documentType=models.CharField(max_length=100)
    prefix=models.CharField(max_length=20)
    period=models.PositiveIntegerField(default=0)
    nextSequence=models.PositiveBigIntegerField(default=1)
    padding=models.PositiveSmallIntegerField(default=6)
    active=models.BooleanField(default=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['organization','documentType','period'],name='code_sequence_scope')]
