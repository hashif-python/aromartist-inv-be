from pathlib import Path
import ast, shutil
from datetime import datetime
base=Path(__file__).resolve().parent/'apps/erp'
paths={n:base/(n+'.py') for n in ('services','direct_perfume','direct_views')}
s,d,v=[paths[n].read_text() for n in paths]
if 'POS_READ_CACHE' not in s:
    anchor="def owned(model,value,user,field='pk'):"
    assert s.count(anchor)==1
    s=s.replace(anchor,'''from contextvars import ContextVar
from contextlib import contextmanager
POS_READ_CACHE = ContextVar('pos_read_cache', default=None)

@contextmanager
def pos_read_cache(user):
    token=POS_READ_CACHE.set((user, {}, {}))
    try: yield
    finally: POS_READ_CACHE.reset(token)

'''+anchor+'''
    state=POS_READ_CACHE.get()
    if state is not None and state[0] is user and field=='pk' and model.__name__ in ('Material','Fragrance','BottleSize'):
        from apps.accounts.access import scoped_erp
        cache=state[1]
        if model not in cache:
            qs=scoped_erp(model.objects.filter(organization=user.organization),user)
            if model.__name__=='Material': qs=qs.select_related('categoryRef','subcategoryRef')
            cache[model]={str(obj.pk):obj for obj in qs}
        obj=cache[model].get(str(value))
        if obj is None: raise ValidationError({field:f'{model.__name__} does not exist in your organization.'})
        return obj
''')
if 'def pos_stock_balances(' not in d:
    anchor='def producible_stock(product,user,location=None):'
    assert d.count(anchor)==1
    d=d.replace(anchor,'''def pos_stock_balances(user, location):
    state=s.POS_READ_CACHE.get()
    key=location.pk if location is not None else None
    if state is not None and state[0] is user and key in state[2]: return state[2][key]
    stocks=s.scoped_stocks(user).filter(variant__isnull=True,location__status='active',location__isVirtual=False,material__status='active')
    if location is not None: stocks=stocks.filter(location=location)
    balances=defaultdict(lambda: defaultdict(Decimal))
    for loc,material,qty in stocks.values_list('location_id','material_id','quantity'):
        balances[loc][material]+=qty
    if state is not None and state[0] is user: state[2][key]=balances
    return balances

'''+anchor)
    start=d.index(anchor); end=d.index('\ndef ',start+len(anchor)); block=d[start:end]
    a=block.index('    stocks=s.scoped_stocks'); b=block.index('    return sum(',a)
    block=block[:a]+'    balances=pos_stock_balances(user,location)\n'+block[b:]; d=d[:start]+block+d[end:]
    old="m.Stock.objects.filter(organization=user.organization,location=branch,material=material).values_list('quantity',flat=True).first() or Decimal(0) if branch else None"
    assert d.count(old)==2
    d=d.replace(old,"pos_stock_balances(user,branch).get(branch.pk,{}).get(material.pk,Decimal(0)) if branch else None")
if 'with s.pos_read_cache(request.user):' not in v:
    import re
    pattern=r'(?m)^(\s*)values=\[product_data\(p,request.user,branch\) for p in (qs[^\n]*)\]$'
    match=re.search(pattern,v); assert match, 'Unsupported catalogue view; no changes made'
    indent,expr=match.groups(); expr=expr.replace('qs','qs.select_related("fragranceId")',1)
    v=v[:match.start()]+indent+'with s.pos_read_cache(request.user):\n'+indent+'    values=[product_data(p,request.user,branch) for p in '+expr+']'+v[match.end():]
for content in (s,d,v): ast.parse(content)
for n,content in zip(paths,(s,d,v)):
    p=paths[n]
    if p.read_text()!=content:
        shutil.copy2(p,p.with_suffix('.py.before_pos_'+datetime.now().strftime('%Y%m%d%H%M%S')));p.write_text(content);print('Updated',p)
