from pathlib import Path
import ast
from datetime import datetime
root=Path(__file__).resolve().parent
base=root/'apps/erp'
if not base.exists(): base=root/'backend/apps/erp'
serializer=base/'serializers.py'; views=base/'direct_views.py'
s=serializer.read_text(); v=views.read_text()
marker='class BulkProductListSerializer'
if marker not in s:
    anchor='class ProductSerializer(TenantSerializer):'
    assert s.count(anchor)==1
    s=s.replace(anchor,'''class BulkProductListSerializer(serializers.ListSerializer):
    def to_representation(self, data):
        from collections import defaultdict
        from django.db.models import Count
        from .services import scoped_stocks
        from .direct_perfume import requirements, perfume_stock_location
        user=self.context['request'].user
        if hasattr(data, 'all'): data=data.all()
        if hasattr(data, 'select_related'): data=data.select_related('fragranceId')
        products=list(data)
        if not products: return []
        ids=[p.pk for p in products]
        counts=dict(m.Variant.objects.filter(productId_id__in=ids).values('productId_id').annotate(n=Count('pk')).values_list('productId_id','n'))
        stocks=scoped_stocks(user)
        finished=dict(stocks.filter(variant__productId_id__in=ids).values('variant__productId_id').annotate(n=Sum('quantity')).values_list('variant__productId_id','n'))
        raw=stocks.filter(variant__isnull=True,location__status='active',location__isVirtual=False,material__status='active')
        if user.organization.singleLocationMode:
            raw=raw.filter(location=perfume_stock_location(user,None))
        balances=defaultdict(lambda: defaultdict(Decimal))
        for loc,key,qty in raw.values_list('location_id','material_id','quantity'):
            balances[loc][key]+=qty
        available={}
        for p in products:
            if not p.directBlend: available[p.pk]=finished.get(p.pk,ZERO); continue
            available[p.pk]=0
            if p.status!='active' or not p.bottleSizeRef_id or len(p.packagingRecipe)<3 or not p.recipe: continue
            required=defaultdict(Decimal)
            for row in requirements(p,Decimal(1)):
                if row['quantity']<=0: break
                required[row['materialId']]+=row['quantity']
            else:
                if required: available[p.pk]=sum(max(0,min(int(amounts[key]//qty) for key,qty in required.items())) for amounts in balances.values())
        self.child._bulk_product_metrics=(counts,finished,available)
        try: return super().to_representation(products)
        finally: del self.child._bulk_product_metrics

'''+anchor)
    start=s.index(anchor); end=s.index('\nclass ',start+len(anchor)); block=s[start:end]
    block=block.replace('    def get_availableStock(self,o):','    def get_availableStock(self,o):\n        if hasattr(self,"_bulk_product_metrics"): return self._bulk_product_metrics[2].get(o.pk,0)')
    block=block.replace('def get_variantsCount(self,o): return o.variants.count()','def get_variantsCount(self,o):\n        if hasattr(self,"_bulk_product_metrics"): return self._bulk_product_metrics[0].get(o.pk,0)\n        return o.variants.count()')
    block=block.replace('    def get_finishedStock(self,o):','    def get_finishedStock(self,o):\n        if hasattr(self,"_bulk_product_metrics"): return self._bulk_product_metrics[1].get(o.pk,ZERO)')
    block=block.replace('        model=m.Product','        model=m.Product\n        list_serializer_class=BulkProductListSerializer')
    assert 'list_serializer_class=BulkProductListSerializer' in block and '_bulk_product_metrics[0]' in block
    s=s[:start]+block+s[end:]
if 'catalogueSummary' not in v:
    anchor="        if pk:qs=qs.filter(pk=pk)"
    assert v.count(anchor)==1
    v=v.replace(anchor,anchor+'''
        if not pk and request.query_params.get('catalogueSummary')=='1' and branch is None:
            from .serializers import ProductSerializer
            records=ProductSerializer(qs,many=True,context={'request':request}).data
            return Response([dict(id=p['id'],name=p['name'],code=p['code'],fragranceName=p.get('fragranceName',''),fillVolumeMl=p['fillVolumeMl'],sellingPrice=p['sellingPrice'],status=p['status'],available=p['availableStock']) for p in records])''')
    # summary search is handled client-side, do not use this option for POS
ast.parse(s);ast.parse(v)
for path,content in [(serializer,s),(views,v)]:
    if path.read_text()!=content:
        backup=path.with_suffix(path.suffix+'.before_perf_'+datetime.now().strftime('%Y%m%d%H%M%S'))
        backup.write_text(path.read_text());path.write_text(content)
        print('Updated',path,'Backup',backup)
    else: print('Already updated',path)
