from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied,ValidationError
from django.shortcuts import get_object_or_404
from apps.accounts.permissions import has
from apps.erp.models import Location,Product
from .models import Offer
from .serializers import OfferSerializer
from .services import available,calculate

def manager(user):
    if not (user.is_superuser or has(user,'sales.pos') and has(user,'pos.discount.apply')):raise PermissionDenied('Offer management permission required.')
class Offers(APIView):
    def get(self,request):
        branch=request.query_params.get('branchId')
        qs=Offer.objects.filter(organization=request.user.organization)
        if not (request.user.is_superuser or has(request.user,'pos.discount.apply')):
            qs=qs.filter(status='active',automatic=True)
        if branch:
            qs=qs.filter(models.Q(branches__isnull=True)|models.Q(branches__pk=branch)).distinct()
        return Response(OfferSerializer(qs.order_by('-priority','name'),many=True).data)
    def post(self,request):
        manager(request.user)
        serializer=OfferSerializer(data=request.data,context={"request":request});serializer.is_valid(raise_exception=True)
        obj=serializer.save(organization=request.user.organization)
        return Response(OfferSerializer(obj).data,status=201)
from django.db import models
class OfferDetail(APIView):
    def patch(self,request,pk):
        manager(request.user)
        obj=get_object_or_404(Offer,pk=pk,organization=request.user.organization)
        serializer=OfferSerializer(obj,data=request.data,partial=True,context={"request":request});serializer.is_valid(raise_exception=True);serializer.save()
        return Response(serializer.data)
class Preview(APIView):
    def post(self,request):
        branch=get_object_or_404(Location,pk=request.data.get('branchId'),organization=request.user.organization,kind='Branch',isVirtual=False)
        rows=request.data.get('cart',[])
        if not isinstance(rows,list) or len(rows)>100:raise ValidationError('Invalid cart.')
        ids=[r.get('productId') for r in rows]
        products={str(p.pk):p for p in Product.objects.filter(organization=request.user.organization,pk__in=ids,status='active')}
        if len(products)!=len(set(ids)):raise ValidationError('Invalid products.')
        lines=[{'productId':r['productId'],'qty':r['qty'],'rate':products[str(r['productId'])].sellingPrice} for r in rows]
        result=calculate(request.user.organization,branch,lines)
        subtotal=sum((l['rate']*l['qty'] for l in lines),0)
        return Response({'subtotal':str(subtotal),'discount':str(result['discount'] if result else 0),'total':str(subtotal-(result['discount'] if result else 0)),'offer':{'id':result['offer'].pk,'name':result['offer'].name} if result else None})
