from django.db import transaction
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from drf_spectacular.utils import extend_schema
from apps.accounts.models import Organization
from apps.accounts.access import scoped_erp
from . import models as m,services as s
from .direct_perfume import permit,save_product,product_data,sale_branch,usage,requirements
from .pricing import TYPES

@extend_schema(exclude=True)
class PerfumeProducts(APIView):
    def get(self,request,pk=None):
        permit(request.user,'inventory.product.view','inventory.view','sales.invoice.checkout','sales.pos','pos.stock.view')
        branch=sale_branch(request.user,request.query_params) if request.query_params.get('branchId') else None
        qs=m.Product.objects.filter(organization=request.user.organization,directBlend=True).order_by('name')
        if pk:qs=qs.filter(pk=pk)
        if request.query_params.get('search'):qs=qs.filter(name__icontains=request.query_params['search'][:120])
        values=[product_data(p,request.user,branch) for p in qs[:200]]
        if pk:
            if not values:raise ValidationError('Product was not found.')
            return Response(values[0])
        return Response(values)
    @transaction.atomic
    def post(self,request,pk=None):
        product=save_product(request.user,request.data,s.owned(m.Product,pk,request.user) if pk else None)
        branch=sale_branch(request.user,request.data) if request.data.get('branchId') or (request.user.branch_id and request.user.branch.isVirtual) else None
        return Response(product_data(product,request.user,branch),status=200 if pk else 201)
    def patch(self,request,pk):return self.post(request,pk)

@extend_schema(exclude=True)
class BlendWorkspace(APIView):
    def get(self,request):
        permit(request.user,'inventory.product.view','inventory.view','sales.invoice.checkout','sales.pos','pos.stock.view')
        branches=scoped_erp(m.Location.objects.filter(organization=request.user.organization,kind='Branch',status='active'),request.user)
        materials=m.Material.objects.filter(organization=request.user.organization,status='active',unit='ml').select_related('categoryRef')
        from .category_utils import material_type
        fragrances=m.Fragrance.objects.filter(organization=request.user.organization,status='active').order_by('name')
        bottles=m.BottleSize.objects.filter(organization=request.user.organization,status='active').order_by('volumeMl','name')
        return Response(dict(fragrances=[dict(id=f.pk,name=f.name,perfumeOilId=f.perfumeOilId_id,pricesByType=f.pricesByType) for f in fragrances],fragranceTypes=[dict(code=k,name=v[0],minOil=v[1],maxOil=v[2]) for k,v in TYPES.items()],bottleSizes=[dict(id=b.pk,name=b.name,volumeMl=str(b.volumeMl),packaging=[dict(materialId=getattr(b,field+'_id'),name=getattr(b,field).name if getattr(b,field+'_id') else '',role=role) for role,field in [('Bottle','bottleMaterialRef'),('Cap','capMaterialRef'),('Pump / atomizer','pumpMaterialRef'),('Label','labelMaterialRef'),('Dip tube','dipTubeMaterialRef')] if getattr(b,field+'_id')],configured=bool(b.bottleMaterialRef_id and b.capMaterialRef_id and b.pumpMaterialRef_id and b.labelMaterialRef_id)) for b in bottles],branches=[dict(id=b.pk,name=b.name,code=b.code,isVirtual=b.isVirtual,physicalBranches=list(b.physicalBranches.values_list('pk',flat=True))) for b in branches],materials=[dict(id=x.pk,name=x.name,type=material_type(x),fragrancePrices=x.fragrancePrices) for x in materials if material_type(x) in {'Perfume Oil','Solvent'}]))

@extend_schema(exclude=True)
class BlendQuote(APIView):
    @transaction.atomic
    def post(self,request):
        permit(request.user,'sales.invoice.checkout','sales.pos')
        from .direct_perfume import prepare_lines,requirements as product_requirements
        from collections import defaultdict
        from decimal import Decimal
        branch=sale_branch(request.user,request.data);cart=request.data.get('cart')
        if not isinstance(cart,list) or not cart or len(cart)>100 or any(not isinstance(r,dict) or not r.get('productId') for r in cart):raise ValidationError('Add recipe products to the cart.')
        products=prepare_lines(request.user,branch,cart,lock=False);requirements=defaultdict(lambda:Decimal(0));total=Decimal(0)
        for row in cart:
            product=products[row['productId']];qty=s.integer(row.get('qty'));total+=product._pricing['price']*qty
            for required in product_requirements(product,qty):requirements[required['materialId']]+=required['quantity']
        return Response(s.json_num(dict(branchId=branch.pk,total=s.cash(total),tax=0,ingredients=[dict(materialId=k,name=m.Material.objects.get(pk=k).name,required=q,available=m.Stock.objects.get(location=s.stock_location(request.user,branch),material_id=k).quantity,unit=m.Material.objects.get(pk=k).unit) for k,q in sorted(requirements.items())])))

@extend_schema(exclude=True)
class BlendStatus(APIView):
    def get(self,request):
        permit(request.user,'sales.invoice.checkout','sales.pos')
        key=request.query_params.get('checkoutKey','')
        from apps.accounts.permissions import has
        qs=scoped_erp(m.Invoice.objects.filter(organization=request.user.organization,checkoutKey=key),request.user)
        if not has(request.user,'*'):qs=qs.filter(salesperson=request.user)
        invoice=qs.first() if key else None
        from .serializers import InvoiceSerializer
        return Response(dict(invoice=InvoiceSerializer(invoice,context={'request':request}).data if invoice else None))


@extend_schema(exclude=True)
class FragrancePricing(APIView):
    def post(self,request):
        permit(request.user,'inventory.product.view','inventory.product.create','inventory.product.edit','sales.invoice.checkout','sales.pos')
        if request.data.get('branchId') or (request.user.branch_id and request.user.branch.isVirtual):sale_branch(request.user,request.data)
        from .pricing import calculate
        result=calculate(request.user,request.data)
        return Response(s.json_num(dict(sellingPrice=result['price'],pricing=result['snapshot'],pricingToken=result['token'])))
