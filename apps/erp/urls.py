from django.urls import path
from rest_framework.routers import DefaultRouter
from .views import *
from .projections import Projection, BalanceView
router=DefaultRouter()
for prefix,cls in [('inventory/categories',MaterialCategoryViewSet),('warehouses',LocationViewSet),('branches',BranchViewSet),('suppliers',SupplierViewSet),('customers',CustomerViewSet),('inventory/raw-materials',MaterialViewSet),('inventory/movements',MovementViewSet),('inventory/adjustments',AdjustmentViewSet),('inventory/wastage',WastageViewSet),('fragrances',FragranceViewSet),('concentrations',ConcentrationViewSet),('bottle-sizes',BottleSizeViewSet),('formulas',FormulaViewSet),('products/variants',VariantViewSet),('products',ProductViewSet),('production/batches',BatchViewSet),('transfers',TransferViewSet),('purchases/orders',PurchaseOrderViewSet),('purchases/grn',ReceiptViewSet),('purchases/bills',BillViewSet),('purchases/returns',PurchaseReturnViewSet),('sales/invoices',InvoiceViewSet),('sales/returns',SalesReturnViewSet),('finance/expenses',ExpenseViewSet),('finance/transactions',LedgerViewSet),('finance/manual-income',LedgerViewSet)]: router.register(prefix,cls,basename=prefix.replace('/','-'))
urlpatterns=[]
for url,mode,read,write in [('inventory/stock-overview/','stock',['inventory.view'],['*']),('inventory/low-stock/','low',['inventory.view'],['*']),('production/check-availability/','availability',['production.view'],['production.add_batch']),('sales/pos/checkout/','checkout',['sales.view'],['sales.pos']),('dashboard/summary/','dashboard',['inventory.view','sales.view','finance.view','production.view'],['*']),('dashboard/alerts/','alerts',['inventory.view','sales.view','finance.view','production.view'],['*']),('reports/summary/','reports',['reports.branch','reports.finance'],['*']),('finance/dashboard/','finance',['finance.view'],['*']),('finance/cash-bank/','cash-bank',['finance.view'],['*']),('finance/income/','income',['finance.view'],['finance.view']),('finance/receivables/','receivables',['finance.view'],['finance.receivables']),('finance/payables/','payables',['finance.view'],['finance.payables']),('purchases/payments/','payments',['purchases.view','finance.view'],['finance.payables'])]:
    urlpatterns.append(path(url,Projection.as_view(mode=mode,read_permissions=read,write_permissions=write,http_method_names=['post','options'] if mode in ['availability','checkout'] else ['get','post','options'] if mode=='payments' else ['get','options']),name=mode))
for mode in ['receivables','payables']: urlpatterns.append(path(f'finance/{mode}/<str:pk>/',BalanceView.as_view(mode=mode,http_method_names=['patch','delete','options']),name=mode+'-detail'))
urlpatterns+=router.urls

urlpatterns.insert(0,path('finance/income/<str:pk>/',LedgerViewSet.as_view({'patch':'partial_update','delete':'destroy'}),name='income-detail'))

from .direct_views import PerfumeProducts,BlendWorkspace
urlpatterns += [path("perfume-products/",PerfumeProducts.as_view()),path("perfume-products/<str:pk>/",PerfumeProducts.as_view()),path("perfume-workspace/",BlendWorkspace.as_view())]

from .direct_views import BlendQuote,BlendStatus
urlpatterns += [path("perfume-quote/",BlendQuote.as_view()),path("perfume-status/",BlendStatus.as_view())]

from .direct_views import FragrancePricing
urlpatterns += [path('perfume-pricing/',FragrancePricing.as_view())]
