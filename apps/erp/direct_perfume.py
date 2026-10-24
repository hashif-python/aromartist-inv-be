"""Product-attached blend definitions; all inventory posting uses existing ERP services."""
from decimal import ROUND_CEILING, Decimal,ROUND_HALF_UP
from collections import defaultdict
from django.db import transaction
from rest_framework.exceptions import ValidationError,PermissionDenied
from apps.accounts.permissions import has
from . import models as m,services as s
from .category_utils import material_type,packaging_type

def permit(user,*codes):
    if not any(has(user,c) for c in codes):raise PermissionDenied('This action is not permitted.')

def sale_branch(user,data):
    selected=s.location(user,data.get('branchId') or data.get('branchName'),'Branch')
    if not selected.isVirtual:return selected
    target=data.get('physicalBranchId')
    if not target:raise ValidationError('Select Branch 1 or Branch 2 before posting from the virtual branch.')
    physical=s.location(user,target,'Branch')
    if physical.isVirtual or not selected.physicalBranches.filter(pk=physical.pk).exists():raise ValidationError('Select an authorized physical branch linked to this virtual branch.')
    return physical

def recipe(user,rows):
    if not isinstance(rows,list) or not 2<=len(rows)<=100:raise ValidationError('Add two or more oil/solvent ingredients.')
    result=[];seen=set();total=Decimal(0);types=set()
    for row in rows:
        if not isinstance(row,dict):raise ValidationError('Invalid ingredient.')
        material=s.owned(m.Material,row.get('materialId'),user);kind=material_type(material)
        percentage=s.D(row.get('percentage'),True)
        if material.pk in seen:raise ValidationError('Each ingredient can be selected only once.')
        if material.status!='active' or material.unit!='ml' or kind not in {'Perfume Oil','Solvent'}:raise ValidationError(f'{material.name}: choose an active oil or solvent measured in ml.')
        if percentage>100:raise ValidationError('Percentage cannot exceed 100%.')
        seen.add(material.pk);types.add(kind);total+=percentage
        normalized=dict(materialId=material.pk,percentage=str(percentage))
        if row.get('fragranceId'):
            fragrance=s.owned(m.Fragrance,row['fragranceId'],user)
            if kind!='Perfume Oil' or fragrance.status!='active' or fragrance.perfumeOilId_id!=material.pk:raise ValidationError('Select an active fragrance linked to this oil.')
            normalized['fragranceId']=fragrance.pk
        result.append(normalized)
    if total!=100:raise ValidationError(f'Formulation total must equal exactly 100%; current total {total}%.')
    if types!={'Perfume Oil','Solvent'}:raise ValidationError('Include at least one perfume oil and one solvent.')
    return result

@transaction.atomic
def save_product(user,data,instance=None):
    permit(user,'inventory.product.edit') if instance else permit(user,'inventory.product.create')
    from apps.accounts.models import Organization
    Organization.objects.select_for_update().get(pk=user.organization_id)
    if instance:
        instance=m.Product.objects.select_for_update().get(pk=instance.pk)
        if not instance.directBlend:raise ValidationError('Legacy products are preserved; create a new recipe product.')
        if data.get('recipeRevision')!=instance.recipeRevision:raise ValidationError('Product changed. Reload before saving.')
    name=str(data.get('name','')).strip();price=s.D(data.get('sellingPrice',0));volume=s.D(data.get('fillVolumeMl',instance.fillVolumeMl if instance else 1),True);minimum=Decimal(0)
    if not name or len(name)>160 or volume>10000 :raise ValidationError('Enter name, bottle volume up to 10000 ml and a positive selling price; minimum must not exceed selling price.')
    duplicates=m.Product.objects.filter(organization=user.organization,directBlend=True,name__iexact=name)
    if instance:duplicates=duplicates.exclude(pk=instance.pk)
    if duplicates.exists():raise ValidationError('A perfume product with this name already exists. Use a distinct name for a customer-specific recipe.')
    rows=recipe(user,data.get('recipe'))
    fragrance=None
    fragrance_id=data.get('fragranceId',instance.fragranceId_id if instance else None)
    if fragrance_id:
        fragrance=s.owned(m.Fragrance,fragrance_id,user)
        if fragrance.status!='active' and (not instance or instance.fragranceId_id!=fragrance.pk):raise ValidationError('Choose an active fragrance.')
    bottle_id=data.get('bottleSizeId',instance.bottleSizeRef_id if instance else None)
    bottle=None;packaging=[]
    if bottle_id:
        bottle=s.owned(m.BottleSize,bottle_id,user)
        if bottle.status!='active':raise ValidationError('Choose an active bottle size.')
        volume=bottle.volumeMl
        if volume<=0 or volume>10000:raise ValidationError('Bottle volume must be between 0 and 10000 ml.')
        packaging=instance.packagingRecipe if instance and instance.bottleSizeRef_id==bottle.pk and instance.packagingRecipe and not data.get('refreshPackaging') else packaging_for(user,bottle)
    elif not instance:
        raise ValidationError('Select a bottle with bottle, cap and pump configured in Bottle Setup.')
    elif instance.packagingRecipe:
        raise ValidationError('Select a bottle size for this packaged product.')
    fragrance_type=data.get('fragranceType',instance.fragranceType if instance else '')
    calculated=None
    if fragrance_type:
        from .pricing import calculate
        calculated=calculate(user,{**data,'fragranceType':fragrance_type,'recipe':rows,'bottleSizeId':bottle.pk if bottle else None,'pricingMode':data.get('pricingMode','auto')},lock=True)
        if data.get('pricingToken') and data['pricingToken']!=calculated['token']:raise ValidationError('Pricing changed. Refresh price and review the result before saving.')
        price=calculated['price']
    elif not instance:raise ValidationError('Select a fragrance type for the product.')
    material_ids=[r['materialId'] for r in rows]+[r['materialId'] for r in packaging]
    costs={x.pk:x.currentCost for x in m.Material.objects.select_for_update().filter(organization=user.organization,pk__in=material_ids).order_by('pk')}
    raw_cost=sum((volume*Decimal(r['percentage'])/100).quantize(Decimal('.0001'),rounding=ROUND_HALF_UP)*costs[r['materialId']] for r in rows)
    package_cost=sum(Decimal(r['quantity'])*costs[r['materialId']] for r in packaging)
    minimum=(raw_cost+package_cost).quantize(Decimal('.01'),rounding=ROUND_CEILING)
    if price<=0 or minimum>price:raise ValidationError('Selling price must be positive and cover the automatically calculated ingredient and packaging cost.')
    status=data.get('status','active')
    if status not in {'active','inactive'}:raise ValidationError('Invalid status.')
    values=dict(fragranceType=fragrance_type,pricingMode=data.get('pricingMode','auto') if fragrance_type else 'manual',pricingSnapshot=calculated['snapshot'] if calculated else {},bottleSizeRef=bottle,packagingRecipe=packaging,fragranceId=fragrance,name=name,directBlend=True,fillVolumeMl=volume,sellingPrice=price,minSellingPrice=minimum,recipe=rows,status=status,description=str(data.get('description',''))[:5000],category='Perfume')
    if instance:
        for k,v in values.items():setattr(instance,k,v)
        instance.recipeRevision+=1;instance.save();return instance
    return m.Product.objects.create(organization=user.organization,code='',**values)

def usage(product,qty):
    amount=product.fillVolumeMl*qty
    return [(row['materialId'],(amount*Decimal(row['percentage'])/100).quantize(Decimal('.0001'),rounding=ROUND_HALF_UP),row['percentage']) for row in product.recipe]

def packaging_for(user,bottle):
    rows=[];seen=set()
    for role,field in [('Bottle','bottleMaterialRef'),('Cap','capMaterialRef'),('Pump / atomizer','pumpMaterialRef'),('Label','labelMaterialRef'),('Dip tube','dipTubeMaterialRef')]:
        key=getattr(bottle,field+'_id')
        if not key:
            if role=='Dip tube':continue
            raise ValidationError(f'Configure {role} for {bottle.name} in Bottle Setup.')
        material=s.owned(m.Material,key,user)
        if material.status!='active' or material.unit!='pcs' or material_type(material)!='Packaging':raise ValidationError(f'{role}: choose active Packaging stock measured in pcs.')
        expected={'Pump / atomizer':'Pump','Dip tube':'Dip Tube'}.get(role,role)
        if packaging_type(material)!=expected:raise ValidationError(f'{role}: select a matching packaging subtype in Bottle Setup.')
        if key in seen:raise ValidationError('Bottle, cap, pump and separate dip tube must be distinct stock materials.')
        if material.compatibleBottleSizes.exists() and not material.compatibleBottleSizes.filter(pk=bottle.pk).exists():raise ValidationError(f'{material.name} is not compatible with this bottle.')
        seen.add(key);rows.append(dict(materialId=key,quantity='1',role=role))
    return rows

def requirements(product,qty):
    rows=[dict(materialId=k,quantity=q,unit='ml',percentage=p,kind='ingredient') for k,q,p in usage(product,qty)]
    for row in product.packagingRecipe:
        rows.append(dict(materialId=row['materialId'],quantity=Decimal(row['quantity'])*qty,unit='pcs',role=row['role'],kind='packaging'))
    return rows

def prepare_lines(user,branch,cart,lock=True):
    branch=s.stock_location(user,branch)
    products={};need=defaultdict(lambda:Decimal(0));seen=set()
    for row in cart:
        if not row.get('productId'):continue
        product=s.owned(m.Product,row['productId'],user);product=(m.Product.objects.select_for_update() if lock else m.Product.objects).get(pk=product.pk)
        if product.pk in seen:raise ValidationError('Duplicate product cart lines are not allowed.')
        seen.add(product.pk)
        if not product.directBlend or product.status!='active':raise ValidationError('Select an active recipe product.')
        if row.get('recipeRevision')!=product.recipeRevision:raise ValidationError(f'{product.name} changed. Refresh the product and review its recipe/price before checkout.')
        if not product.bottleSizeRef_id or len(product.packagingRecipe)<3:raise ValidationError(f'{product.name}: select a configured bottle in product editing before selling. Bottle, cap and pump stock are required.')
        from .pricing import for_product
        product._pricing=for_product(user,product,lock=lock)
        if product.fragranceType and row.get('pricingToken')!=product._pricing['token']:raise ValidationError(f'{product.name}: pricing changed. Refresh the product and review the price before checkout.')
        recipe(user,product.recipe);qty=s.integer(row.get('qty'));products[product.pk]=product
        for required in requirements(product,qty):
            key=required['materialId'];quantity=required['quantity']
            material=s.owned(m.Material,key,user)
            if required['kind']=='packaging' and packaging_type(material)!={'Pump / atomizer':'Pump','Dip tube':'Dip Tube'}.get(required['role'],required['role']):raise ValidationError(f'{material.name}: packaging subtype no longer matches its saved role.')
            if material.unit!=required['unit'] or material.status!='active' or (required['kind']=='packaging' and material_type(material)!='Packaging'):raise ValidationError(f'{material.name}: stock material is inactive or has changed type/unit.')
            if quantity<=0:raise ValidationError('Ingredient quantity is below stock precision; increase volume or percentage.')
            need[key]+=quantity
    errors=[]
    for key,quantity in sorted(need.items()):
        material=s.owned(m.Material,key,user);available=s.stock_for(user,branch,material).quantity if lock else (m.Stock.objects.filter(organization=user.organization,location=branch,material=material).values_list('quantity',flat=True).first() or Decimal(0))
        if available<quantity:errors.append(dict(materialId=key,name=material.name,required=str(quantity),available=str(available),unit=material.unit))
    if errors:raise ValidationError({'detail':'Insufficient stock: '+ '; '.join(f"{r['name']} required: {r['required']}{r['unit']}, available: {r['available']}{r['unit']}" for r in errors),'materials':errors})
    return products

def post_line(user,branch,invoice,row,products):
    branch=s.stock_location(user,branch)
    product=products[row['productId']];qty=s.integer(row.get('qty'));discount=s.D(row.get('discount',0));rate=product._pricing['price'];total=rate*qty-discount
    if total<0 or total/qty<product.minSellingPrice:raise ValidationError('Discount breaches minimum selling price.')
    snapshot=[];packaging_snapshot=[];cost=Decimal(0)
    for key,amount,percentage in usage(product,qty):
        material=s.owned(m.Material,key,user);cost+=amount*material.currentCost
        snapshot.append(dict(materialId=key,name=material.name,percentage=percentage,quantity=str(amount),unit='ml',fillVolumeMl=str(product.fillVolumeMl),revision=product.recipeRevision))
        s.post_stock(user,branch,material,-amount,'POS_BLEND',invoice.invoiceNumber,f'Blend {product.code}: {qty} x {product.fillVolumeMl} ml')
    for required in requirements(product,qty):
        if required['kind']!='packaging':continue
        material=s.owned(m.Material,required['materialId'],user);amount=required['quantity'];cost+=amount*material.currentCost
        packaging_snapshot.append(dict(materialId=material.pk,name=material.name,role=required['role'],quantity=str(amount),unit='pcs'))
        s.post_stock(user,branch,material,-amount,'POS_PACKAGING',invoice.invoiceNumber,f'Packaging {product.code}: {qty} bottles')
    return m.InvoiceLine.objects.create(organization=user.organization,invoice=invoice,product=product,productName=product.name,sku=product.code,qty=qty,rate=rate,discount=discount,total=total,costSnapshot=s.cash(cost/qty),recipeSnapshot=snapshot,packagingSnapshot=packaging_snapshot,pricingSnapshot=product._pricing['snapshot'])

def product_data(product,user,branch=None):
    if user.organization.singleLocationMode:branch=s.stock_location(user,branch)
    rows=[];available=None
    for row in product.recipe:
        material=s.owned(m.Material,row['materialId'],user)
        balance=m.Stock.objects.filter(organization=user.organization,location=branch,material=material).values_list('quantity',flat=True).first() or Decimal(0) if branch else None
        per=(product.fillVolumeMl*Decimal(row['percentage'])/100).quantize(Decimal('.0001'),rounding=ROUND_HALF_UP)
        if branch and per>0:available=min(available,int(balance//per)) if available is not None else int(balance//per)
        rows.append(dict(**row,name=material.name,type=material_type(material),unit='ml',available=balance))
    packaging=[]
    for r in product.packagingRecipe:
        material=s.owned(m.Material,r['materialId'],user);balance=m.Stock.objects.filter(organization=user.organization,location=branch,material=material).values_list('quantity',flat=True).first() or Decimal(0) if branch else None
        if branch:available=min(available,int(balance//Decimal(r['quantity']))) if available is not None else int(balance//Decimal(r['quantity']))
        packaging.append(dict(**r,name=material.name,unit='pcs',available=balance))
    if not product.bottleSizeRef_id or len(product.packagingRecipe)<3:available=0
    from .pricing import for_product
    pricing_error=''
    try:pricing=for_product(user,product)
    except ValidationError as error:
        pricing_error=str(error.detail);available=0;pricing=dict(price=product.sellingPrice,snapshot=product.pricingSnapshot,token='')
    return s.json_num(dict(pricingError=pricing_error,fragranceType=product.fragranceType,pricingMode=product.pricingMode,pricing=pricing['snapshot'],pricingToken=pricing['token'],bottleSizeId=product.bottleSizeRef_id,packaging=packaging,id=product.pk,name=product.name,code=product.code,fragranceId=product.fragranceId_id,fragranceName=product.fragranceId.name if product.fragranceId_id else '',fillVolumeMl=product.fillVolumeMl,sellingPrice=pricing['price'],minSellingPrice=product.minSellingPrice,description=product.description,status=product.status,recipeRevision=product.recipeRevision,recipe=rows,available=available or 0))
