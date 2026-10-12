"""One authoritative selling-price policy for product forms, POS and invoices.
All type prices are entered for a 100 ml perfume. No selling prices are seeded.
"""
from decimal import Decimal
import hashlib,json
from rest_framework.exceptions import ValidationError
from . import models as m,services as s
from .category_utils import material_type
TYPES={'PARFUM':('Parfum / Extrait de Parfum',15,40),'EDP':('Eau de Parfum (EDP)',15,20),'EDT':('Eau de Toilette (EDT)',5,15),'EDC':('Eau de Cologne (EDC)',2,5),'EAU_FRAICHE':('Eau Fraiche',1,3)}

def prices(values):
    if not isinstance(values,dict) or any(k not in TYPES for k in values):raise ValidationError('Use the supported fragrance type codes for prices.')
    return {k:str(s.D(v,True)) for k,v in values.items() if v not in ('',None)}

def calculate(user,data,validate_recipe=True,lock=False):
    kind=data.get('fragranceType')
    if kind not in TYPES:raise ValidationError('Select Parfum, EDP, EDT, EDC or Eau Fraiche.')
    bottle=s.owned(m.BottleSize,data.get('bottleSizeId'),user)
    if lock:bottle=m.BottleSize.objects.select_for_update().get(pk=bottle.pk)
    if bottle.status!='active':raise ValidationError('Select an active bottle package.')
    from .direct_perfume import recipe
    rows=recipe(user,data.get('recipe')) if validate_recipe else data['recipe']
    if lock:
        list(m.Material.objects.select_for_update().filter(organization=user.organization,pk__in=[r['materialId'] for r in rows]).order_by('pk'))
        list(m.Fragrance.objects.select_for_update().filter(organization=user.organization,pk__in=[r['fragranceId'] for r in rows if r.get('fragranceId')]).order_by('pk'))
        rows=recipe(user,rows)
    selected=[];oil_total=Decimal(0)
    for row in rows:
        material=s.owned(m.Material,row['materialId'],user)
        if material_type(material)!='Perfume Oil':continue
        oil_total+=Decimal(row['percentage'])
        fragrance=s.owned(m.Fragrance,row['fragranceId'],user) if row.get('fragranceId') else None
        if fragrance and (fragrance.status!='active' or fragrance.perfumeOilId_id!=material.pk):raise ValidationError('Selected fragrance must match the selected active oil.')
        tier=fragrance.pricesByType.get(kind) if fragrance else None
        source='Fragrance profile' if tier not in (None,'') else 'Raw oil'
        if tier in (None,''):tier=material.fragrancePrices.get(kind)
        if tier in (None,''):raise ValidationError(f'{fragrance.name if fragrance else material.name}: configure a {TYPES[kind][0]} selling price before using this type.')
        selected.append(dict(materialId=material.pk,fragranceId=fragrance.pk if fragrance else None,name=fragrance.name if fragrance else material.name,price=str(s.D(tier,True)),source=source))
    lower,upper=TYPES[kind][1:]
    if not lower<=oil_total<=upper:raise ValidationError(f'{TYPES[kind][0]} requires total oil between {lower}% and {upper}%; current oil {oil_total}%.')
    highest=max(selected,key=lambda x:Decimal(x['price']))
    multiplier=bottle.priceMultiplier if bottle.priceMultiplier is not None else bottle.volumeMl/Decimal(100)
    calculated=s.cash(Decimal(highest['price'])*multiplier+bottle.priceSurcharge)
    if calculated<=0 or calculated>Decimal('9999999999999'):raise ValidationError('Calculated price is outside supported limits. Review the bottle pricing rule.')
    mode=data.get('pricingMode','auto')
    if mode not in {'auto','override'}:raise ValidationError('Select automatic pricing or an explicit selling-price override.')
    final=s.cash(s.D(data.get('sellingPrice'),True)) if mode=='override' else calculated
    snapshot=dict(currency='INR',fragranceType=kind,typeName=TYPES[kind][0],oilPercentage=str(oil_total),referenceVolumeMl='100',selectedFragrances=selected,highestFragrance=highest['name'],basePrice=highest['price'],bottleSizeId=bottle.pk,bottleName=bottle.name,volumeMl=str(bottle.volumeMl),multiplier=str(multiplier),surcharge=str(bottle.priceSurcharge),calculatedPrice=str(calculated),sellingPrice=str(final),pricingMode=mode)
    token=hashlib.sha256(json.dumps(snapshot,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return dict(price=final,snapshot=snapshot,token=token)

def for_product(user,product,lock=False):
    if not product.fragranceType:return dict(price=product.sellingPrice,snapshot=product.pricingSnapshot,token='')
    return calculate(user,dict(fragranceType=product.fragranceType,bottleSizeId=product.bottleSizeRef_id,recipe=product.recipe,pricingMode=product.pricingMode,sellingPrice=product.sellingPrice),lock=lock)
