"""Inventory product workflow. Mutations run inside an atomic API/command transaction."""
from decimal import Decimal
from types import SimpleNamespace
import hashlib,json
from rest_framework.exceptions import ValidationError,PermissionDenied
from apps.accounts.permissions import has
from . import models as m, services as s

from .category_utils import material_type

PACKAGING={'Packaging','Bottle','Pump','Cap','Label','Pouch','Carry Bag','Carton'}
def save_percentage_formula(user,data,instance=None):
    if instance and (m.Batch.objects.filter(formula=instance).exists() or m.Variant.objects.filter(formulaId=instance).exists()):
        raise ValidationError('This recipe is in use. Create a new version to preserve product recipes and production history.')
    frag=s.owned(m.Fragrance,data.get('fragranceId'),user)
    if frag.status!='active': raise ValidationError('Choose an active fragrance.')
    rows=data.get('percentageIngredients',[])
    if not isinstance(rows,list) or not rows: raise ValidationError('Add perfume oil and solvent ingredients.')
    seen=set();total=Decimal(0);types=set();ingredients=[]
    for row in rows:
        if not isinstance(row,dict): raise ValidationError('Each ingredient must be an object.')
        mat=s.owned(m.Material,row.get('materialId'),user);pct=s.D(row.get('percentage'),True)
        if mat.pk in seen: raise ValidationError('Duplicate ingredients are not allowed.')
        if material_type(mat) not in {'Perfume Oil','Solvent'} or mat.unit!='ml' or mat.status!='active': raise ValidationError('Liquid recipes require active Perfume Oil or Solvent materials in ml.')
        if pct>100: raise ValidationError('An ingredient percentage cannot exceed 100.')
        seen.add(mat.pk);types.add(material_type(mat));total+=pct;ingredients.append((mat,pct))
    if total!=100 or types!={'Perfume Oil','Solvent'}: raise ValidationError('Include perfume oil and solvent; percentages must total exactly 100%.')
    code=str(data.get('code','')).strip();name=str(data.get('name','')).strip();version=str(data.get('version','v1.0')).strip();status=data.get('status','active')
    if not name or len(code)>60 or len(name)>160 or not version or len(version)>40 or status not in {'active','inactive'}: raise ValidationError('Enter a valid formulation code, name, version and status.')
    duplicate=m.Formula.objects.filter(organization=user.organization,code=code,version=version)
    if instance: duplicate=duplicate.exclude(pk=instance.pk)
    if duplicate.exists(): raise ValidationError('This formulation code and version already exist.')
    fields=dict(fragranceId=frag,code=code,name=name,version=version,status=status,percentageRecipe=True)
    if instance:
        for k,v in fields.items(): setattr(instance,k,v)
        instance.save();instance.percentages.all().delete()
    else: instance=m.Formula.objects.create(organization=user.organization,**fields)
    for mat,pct in ingredients: m.PercentageIngredient.objects.create(organization=user.organization,formula=instance,material=mat,percentage=pct)
    return instance

def costing(v):
    rows=[];oil=solvent=pack=Decimal(0)
    percentages={r.material_id:r.percentage for r in v.formulaId.percentages.all()} if v.formulaId.percentageRecipe else {}
    for l in s.recipe_lines(v):
        amount=l.qty*l.material.currentCost
        category=material_type(l.material)
        if category=='Perfume Oil': oil+=amount
        elif category=='Solvent': solvent+=amount
        else: pack+=amount
        rows.append(dict(materialId=l.material_id,name=l.material.name,type=category,percentage=percentages.get(l.material_id),qty=l.qty,unit=l.material.unit,rate=l.material.currentCost,cost=s.cash(amount)))
    extra=v.additionalCost if v.formulaId.percentageRecipe else v.formulaId.laborCost+v.formulaId.cleaningAllocation+v.formulaId.otherCost
    total=s.cash(oil+solvent+pack+extra);profit=s.cash(v.sellingPrice-total)
    return dict(rows=rows,perfumeOilCost=s.cash(oil),solventCost=s.cash(solvent),packagingCost=s.cash(pack),additionalProductionCost=extra,totalEstimatedUnitCost=total,sellingPrice=v.sellingPrice,profit=profit,profitMargin=s.cash(profit/v.sellingPrice*100) if v.sellingPrice else 0)

def automatic_packaging(user,size):
    refs=[size.bottleMaterialRef]
    for field,kind in [('pumpMaterialRef','pump'),('capMaterialRef','cap')]:
        mat=getattr(size,field)
        if not mat:
            candidates=[x for x in m.Material.objects.filter(organization=user.organization,status='active',unit='pcs').select_related('categoryRef') if material_type(x)=='Packaging' and kind in (x.category+' '+x.name).lower() and (not x.compatibleBottleSizes.exists() or x.compatibleBottleSizes.filter(pk=size.pk).exists())]
            if len(candidates)!=1: raise ValidationError(f'Set a default {kind} for {size.name} in Bottle Setup; found {len(candidates)} compatible choices.')
            mat=candidates[0]
        if mat.organization_id!=user.organization_id or mat.status!='active' or material_type(mat)!='Packaging' or mat.unit!='pcs' or (mat.compatibleBottleSizes.exists() and not mat.compatibleBottleSizes.filter(pk=size.pk).exists()): raise ValidationError(f'{kind.title()} for {size.name} must be active, compatible packaging in pcs.')
        refs.append(mat)
    if len({mat.pk for mat in refs})!=3: raise ValidationError('Bottle, pump and cap must be distinct materials.')
    return [{'materialId':mat.pk,'qty':1} for mat in refs]

def save_product(user,data,instance=None):
    from .serializers import ProductSerializer
    # Organization lock serializes duplicate codes/SKUs across concurrent unified writes.
    from apps.accounts.models import Organization
    Organization.objects.select_for_update().get(pk=user.organization_id)
    frag=s.owned(m.Fragrance,data.get('fragranceId'),user);formula=s.owned(m.Formula,data.get('formulaId'),user)
    if frag.status!='active' or formula.fragranceId_id!=frag.pk or formula.status!='active' or not formula.percentageRecipe: raise ValidationError('Choose an active percentage formulation for this fragrance.')
    serializer=ProductSerializer(instance,data={k:data[k] for k in ['code','name','category','description','status','fragranceId'] if k in data},context={'request':SimpleNamespace(user=user,query_params={})})
    serializer.is_valid(raise_exception=True);product=serializer.save(organization=user.organization)
    rows=data.get('variants',[])
    if not isinstance(rows,list) or not rows: raise ValidationError('Create at least one variant.')
    seen=set();ids=set()
    for row in rows:
        if not isinstance(row,dict): raise ValidationError('Each variant must be an object.')
        sku=str(row.get('sku','')).strip()
        if len(sku)>80 or (sku and sku in seen): raise ValidationError('Duplicate variant SKU.')
        if sku:seen.add(sku)
        v=None
        if row.get('id'):
            v=s.owned(m.Variant,row['id'],user)
            if v.productId_id!=product.pk: raise ValidationError('Variant belongs to another product.')
            sku=v.sku
        if sku and m.Variant.objects.filter(organization=user.organization,sku=sku).exclude(pk=v.pk if v else '').exists(): raise ValidationError({'sku':f'{sku} already exists.'})
        size=s.owned(m.BottleSize,row.get('bottleSizeId'),user);conc=s.owned(m.Concentration,row.get('concentrationId'),user)
        original_price=row.get('sellingPrice',getattr(v,'sellingPrice',0))
        automatic=row.get('automaticPackaging',False)
        try: planned=int(str(row.get('plannedQuantity',getattr(v,'plannedQuantity',1))))
        except (ValueError,TypeError): raise ValidationError('Perfume quantity must be a positive whole number.')
        if not 1<=planned<=100000000: raise ValidationError('Perfume quantity must be between 1 and 100000000 bottles.')
        if automatic:
            row={**row,'packaging':automatic_packaging(user,size),'fillVolumeMl':size.volumeMl,'sellingPrice':0,'mrp':0,'minSellingPrice':0}
        fill=s.D(row.get('fillVolumeMl'),True)
        if fill>size.volumeMl or size.status!='active' or conc.status!='active': raise ValidationError('Fill volume must fit an active bottle; choose an active concentration.')
        price=s.D(row.get('sellingPrice'));extra=s.D(row.get('additionalCost',0));minimum=s.D(row.get('minSellingPrice',0));status=row.get('status','active')
        if status not in {'active','inactive'} or minimum>price: raise ValidationError('Invalid variant status or minimum selling price.')
        packaging=[];used=set()
        for r in row.get('packaging',[]):
            mat=s.owned(m.Material,r.get('materialId'),user);qty=s.D(r.get('qty'),True)
            if material_type(mat)!='Packaging' or mat.status!='active' or mat.pk in used: raise ValidationError('Choose unique active packaging materials.')
            if mat.compatibleBottleSizes.exists() and not mat.compatibleBottleSizes.filter(pk=size.pk).exists(): raise ValidationError(f'{mat.name} is not compatible with {size.name}.')
            if mat.unit=='pcs' and qty!=qty.to_integral_value(): raise ValidationError('Packaging pieces require whole quantities.')
            used.add(mat.pk);packaging.append((mat,qty))
        if size.bottleMaterialRef_id not in used: raise ValidationError('Include the selected bottle inventory material in packaging.')
        fields=dict(plannedQuantity=planned,productId=product,fragranceId=frag,formulaId=formula,bottleSizeId=size,concentrationId=conc,fillVolumeMl=fill,sku=sku,sellingPrice=price,mrp=s.D(row.get('mrp',price)),minSellingPrice=minimum,additionalCost=extra,minStock=s.D(row.get('minStock',0)),status=status,name=f'{product.name} {fill} ml {conc.code}')
        if v:
            history=m.Batch.objects.filter(variant=v).exists() or m.Movement.objects.filter(stock__variant=v).exists()
            oldpack={(r.material_id,r.qty) for r in v.packaging.all()}
            if history and (any(getattr(v,k)!=fields[k] for k in ['fragranceId','formulaId','bottleSizeId','concentrationId','fillVolumeMl']) or oldpack!={(a.pk,b) for a,b in packaging}): raise ValidationError('Variant recipe and packaging are locked after stock history. Add a new SKU for recipe changes.')
            for k,val in fields.items(): setattr(v,k,val)
            v.save();v.packaging.all().delete()
        else: v=m.Variant.objects.create(organization=user.organization,**fields)
        for mat,qty in packaging: m.VariantPackaging.objects.create(organization=user.organization,variant=v,material=mat,qty=qty)
        if not m.Movement.objects.filter(stock__variant=v).exists(): v.costPrice=costing(v)['totalEstimatedUnitCost'];v.save(update_fields=['costPrice'])
        if automatic and not row.get('id'):
            v.sellingPrice=costing(v)['totalEstimatedUnitCost'];v.mrp=v.sellingPrice;v.save(update_fields=['sellingPrice','mrp'])
        elif automatic and row.get('id'):
            v.sellingPrice=s.D(original_price);v.mrp=v.sellingPrice;v.save(update_fields=['sellingPrice','mrp'])
        ids.add(v.pk)
    # Omitted variants retain history and become inactive rather than being deleted.
    product.variants.exclude(pk__in=ids).update(status='inactive')
    return product

def manufacture(user,product,data):
    if not has(user,'production.complete'): raise PermissionDenied('Production completion permission is required.')
    from apps.accounts.models import Organization
    Organization.objects.select_for_update().get(pk=user.organization_id)
    key=str(data.get('requestKey','')).strip()
    if not key or len(key)>64: raise ValidationError('A production request key is required (maximum 64 characters).')
    fingerprint=hashlib.sha256(json.dumps({k:data.get(k) for k in ['variantId','branchId','sourceWarehouseId','finishedWarehouseId','quantity']},sort_keys=True).encode()).hexdigest()
    existing=m.Batch.objects.filter(organization=user.organization,requestKey=key).first()
    if existing:
        if existing.variant.productId_id!=product.pk or existing.requestFingerprint!=fingerprint: raise ValidationError('Request key was already used for different production details.')
        s.enforce_location(user,existing.warehouse)
        return existing
    v=s.owned(m.Variant,data.get('variantId'),user)
    if v.productId_id!=product.pk or v.status!='active' or v.formulaId.status!='active': raise ValidationError('Choose an active variant of this product.')
    branch=s.location(user,data.get('branchId'),'Branch');src=s.location(user,data.get('sourceWarehouseId'),'Warehouse');dest=s.location(user,data.get('finishedWarehouseId'),'Warehouse');qty=s.integer(data.get('quantity'))
    b=s.create_batch(user,dict(productVariantId=v.pk,warehouseId=src.pk,plannedQty=qty))
    b.branch=branch;b.finishedWarehouse=dest;b.requestKey=key;b.requestFingerprint=fingerprint;b.save()
    return s.complete_batch(user,b,dict(actualProduced=qty))

def workspace(user,product,context):
    from . import serializers as z
    stocks=s.scoped_stocks(user).filter(variant__productId=product).select_related('location','variant')
    batches=m.Batch.objects.filter(variant__productId=product)
    from apps.accounts.access import scoped_erp
    batches=scoped_erp(batches,user)
    return dict(product=z.ProductSerializer(product,context=context).data,variants=z.VariantSerializer(product.variants.all(),many=True,context=context).data,stock=[dict(id=r.pk,variant=r.variant.name,sku=r.variant.sku,location=r.location.name,locationType=r.location.kind,quantity=r.quantity,lowStock=r.quantity<=r.variant.minStock) for r in stocks],production=z.BatchSerializer(batches,many=True,context=context).data,movements=z.MovementSerializer(m.Movement.objects.filter(stock__in=stocks).order_by('-date'),many=True,context=context).data)
