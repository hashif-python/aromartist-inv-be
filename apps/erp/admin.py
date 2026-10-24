from django.contrib import admin
from . import models as m
masters=[m.Location,m.Supplier,m.Customer,m.Material,m.Fragrance,m.Concentration,m.BottleSize,m.Product,m.Variant]
for model in masters:
    fields=[f.name for f in model._meta.fields]
    attrs={'list_display':[k for k in ['name','code','sku','organization','status'] if k in fields],'search_fields':[k for k in ['name','code','sku'] if k in fields],'list_filter':['organization']+(['status'] if 'status' in fields else []),'readonly_fields':['id','created_at','updated_at']}
    admin.site.register(model,type(model.__name__+'Admin',(admin.ModelAdmin,),attrs))
class PostedAdmin(admin.ModelAdmin):
    list_filter=['organization']
    def get_readonly_fields(self,request,obj=None): return [f.name for f in self.model._meta.fields]
    def has_add_permission(self,request): return False
    def has_delete_permission(self,request,obj=None): return False
for model in [m.Formula,m.FormulaLine,m.Stock,m.Movement,m.Batch,m.Consumption,m.Transfer,m.TransferLine,m.PurchaseOrder,m.PurchaseLine,m.Receipt,m.ReceiptLine,m.Bill,m.SupplierPayment,m.PurchaseReturn,m.Invoice,m.InvoiceLine,m.SalesReturn,m.Expense,m.Wastage,m.LedgerEntry,m.BalanceAdjustment]: admin.site.register(model,PostedAdmin)

@admin.register(m.CodeSequence)
class CodeSequenceAdmin(admin.ModelAdmin):
    list_display=['organization','documentType','prefix','period','nextSequence','padding','active']
    readonly_fields=['id','created_at','updated_at','documentType','period','organization','nextSequence']
    def has_add_permission(self,request):return False
    def has_delete_permission(self,request,obj=None):return False
