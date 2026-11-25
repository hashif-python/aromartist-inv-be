"""Resolve fragrance defaults; recipe and pricing remain authoritative on the server."""
from decimal import Decimal, ROUND_HALF_UP
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from . import models as m, services as s
from .category_utils import material_type

PRECISION=Decimal('.0001')
def percentage(value):
    return serializers.DecimalField(max_digits=7,decimal_places=4,min_value=PRECISION,max_value=100).run_validation(value)

def solvent_defaults(user,rows):
    if not isinstance(rows,list) or not 1<=len(rows)<=20:raise ValidationError('Configure one or more default solvents with shares totaling 100%.')
    result=[];seen=set()
    for row in rows:
        if not isinstance(row,dict):raise ValidationError('Invalid solvent default.')
        mat=s.owned(m.Material,row.get('materialId'),user)
        if mat.pk in seen or mat.status!='active' or mat.unit!='ml' or material_type(mat)!='Solvent':raise ValidationError('Default solvents must be distinct active Solvent materials measured in ml.')
        seen.add(mat.pk);result.append(dict(materialId=mat.pk,share=str(percentage(row.get('share')))))
    if sum(Decimal(r['share']) for r in result)!=100:raise ValidationError('Default solvent shares must total exactly 100%.')
    return sorted(result,key=lambda r:r['materialId'])

def defaults(user,kind,target,solvents):
    from .pricing import TYPES
    if kind not in TYPES:raise ValidationError('Configure a default fragrance type first.')
    target=Decimal(20) if kind=='EDP' and target is None else percentage(target)
    if kind=='EDP' and target!=20:raise ValidationError('EDP requires exactly 20% combined oil.')
    lower,upper=TYPES[kind][1:]
    if not lower<=target<=upper:raise ValidationError(f'{kind}: oil concentration must be between {lower}% and {upper}%.')
    return dict(fragranceType=kind,oilPercentage=str(target.quantize(PRECISION)),solvents=solvent_defaults(user,solvents))

def resolve(user,data,lock=False):
    selections=data.get('fragranceSelections')
    if not isinstance(selections,list) or not 1<=len(selections)<=3:raise ValidationError('Select one to three fragrances.')
    if any(not isinstance(r,dict) for r in selections):raise ValidationError('Invalid fragrance selection.')
    ids=[r.get('fragranceId') for r in selections]
    if any(not isinstance(k,str) or not k for k in ids) or len(set(ids))!=len(ids):raise ValidationError('Select distinct fragrances; duplicates are not allowed.')
    if lock:list(m.Fragrance.objects.select_for_update().filter(organization=user.organization,pk__in=ids).order_by('pk'))
    profiles=[s.owned(m.Fragrance,k,user) for k in ids]
    configs=[];oil_rows=[];knots=[]
    for profile in profiles:
        if profile.status!='active':raise ValidationError(f'{profile.name}: select an active fragrance.')
        try:config=defaults(user,profile.defaultType,profile.defaultOilPercentage,profile.solventRecipe)
        except ValidationError as error:raise ValidationError({profile.name:error.detail})
        configs.append(config)
        value=Decimal(config['oilPercentage']) if len(profiles)==1 else percentage(selections[len(configs)-1].get('percentage'))
        oil_rows.append(dict(fragranceId=profile.pk,materialId=profile.perfumeOilId_id,percentage=str(value)))
        for knot in profile.knots.all().order_by('pk'):
            if knot.status!='active':raise ValidationError(f'{profile.name}: remove or reactivate linked Knot {knot.name}.')
            knots.append(dict(fragranceId=profile.pk,id=knot.pk,name=knot.name,description=knot.description,price=str(knot.price),priceBasis=knot.priceBasis,applied=False))
    config=configs[0]
    if any(c!=config for c in configs):raise ValidationError('Selected fragrances have incompatible type, oil concentration or solvent defaults.')
    if len({r['materialId'] for r in oil_rows})!=len(oil_rows):raise ValidationError('Selected fragrances bind the same raw oil. Choose distinct oils.')
    target=Decimal(config['oilPercentage'])
    if sum(Decimal(r['percentage']) for r in oil_rows)!=target:raise ValidationError(f'Combined fragrance oil must equal exactly {target}% of the finished perfume.')
    solvent_total=100-target;remaining=solvent_total;solvent_rows=[]
    for index,row in enumerate(config['solvents']):
        amount=remaining if index==len(config['solvents'])-1 else (solvent_total*Decimal(row['share'])/100).quantize(PRECISION,rounding=ROUND_HALF_UP)
        if amount<=0:raise ValidationError('A solvent share is below supported precision.')
        solvent_rows.append(dict(materialId=row['materialId'],percentage=str(amount)));remaining-=amount
    from .direct_perfume import recipe
    rows=recipe(user,oil_rows+solvent_rows)
    bottle_id=data.get('bottleSizeId')
    if not bottle_id:
        candidates={p.defaultBottleSize_id for p in profiles}
        if len(candidates)==1:bottle_id=next(iter(candidates))
        elif any(candidates):raise ValidationError('Default bottle sets differ. Select the required bottle size.')
    bottle=s.owned(m.BottleSize,bottle_id,user) if bottle_id else None
    if bottle and bottle.status!='active':raise ValidationError('Select an active bottle set.')
    frozen={**config,'fragrances':[dict(id=p.pk,name=p.name) for p in profiles],'knots':knots,'knotChargesApplied':False}
    return {**data,'fragranceFirst':True,'blendConfig':frozen,'fragranceType':config['fragranceType'],
            'fragranceId':profiles[0].pk,'recipe':rows,'bottleSizeId':bottle.pk if bottle else None,
            'fillVolumeMl':str(bottle.volumeMl) if bottle else None}

def quantities(rows,volume,qty=Decimal(1)):
    total=(Decimal(volume)*qty).quantize(PRECISION,rounding=ROUND_HALF_UP)
    values=[(total*Decimal(r['percentage'])/100).quantize(PRECISION,rounding=ROUND_HALF_UP) for r in rows]
    # Put the rounding remainder into the largest solvent row, preserving bottle volume.
    solvent_indexes=[i for i,r in enumerate(rows) if not r.get('fragranceId')]
    if solvent_indexes:values[max(solvent_indexes,key=lambda i:Decimal(rows[i]['percentage']))]+=total-sum(values)
    if any(q<=0 for q in values):raise ValidationError('Ingredient quantity is below supported precision for this bottle.')
    return values
