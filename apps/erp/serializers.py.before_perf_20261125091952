from drf_spectacular.utils import extend_schema_field
from decimal import Decimal
from django.db.models import Sum, Q
from rest_framework import serializers
from . import models as m
from .services import ZERO, json_num, cash
from .category_utils import material_type,packaging_type

class TenantSerializer(serializers.ModelSerializer):
    """Tenant-scoped FK validation applies even to PUT/PATCH and nested masters."""
    def get_fields(self):
        fields=super().get_fields()
        from apps.common.services.code_generator import identifier_fields
        for name in identifier_fields(self.Meta.model):
            if name in fields:fields[name].read_only=True;fields[name].required=False

        user=self.context.get('request').user if self.context.get('request') else None
        for field in fields.values():
            if isinstance(field,serializers.ManyRelatedField): field=field.child_relation
            if isinstance(field,serializers.PrimaryKeyRelatedField) and field.queryset is not None and hasattr(field.queryset.model,'organization'):
                field.queryset=field.queryset.filter(organization_id=user.organization_id) if user and getattr(user,'organization_id',None) else field.queryset.none()
        if user and getattr(user,'organization_id',None) and user.organization.singleLocationMode:
            org=user.organization
            for name,field in fields.items():
                model_field=self.Meta.model._meta.get_field(name) if name in {f.name for f in self.Meta.model._meta.fields} else None
                if self.Meta.model is m.Location and ((name=='warehouse' and getattr(self.context.get('view'),'kind',getattr(self.instance,'kind',None))!='Branch') or (name=='ownerBranch' and getattr(self.context.get('view'),'kind',getattr(self.instance,'kind',None))!='Warehouse')):continue
                if model_field and isinstance(model_field,m.models.ForeignKey) and model_field.related_model is m.Location:
                    target=org.defaultBranch if 'branch' in name.lower() else org.defaultWarehouse
                    if target:field.required=False;field.default=target
        return fields
    def validate(self,attrs):
        for k,v in attrs.items():
            if isinstance(v,Decimal) and (not v.is_finite() or v<0): raise serializers.ValidationError({k:'Enter a nonnegative finite value.'})
        return attrs
    class Meta:
        exclude=['organization','created_at','updated_at']

class LocationSerializer(TenantSerializer):
    warehouseName=serializers.CharField(source='warehouse.name',read_only=True,default='')
    def validate(self,attrs):
        attrs=super().validate(attrs)
        kind=getattr(self.instance,'kind',None) or getattr(self.context.get('view'),'kind',None)
        warehouse=attrs.get('warehouse',getattr(self.instance,'warehouse',None))
        if warehouse and (kind!='Branch' or warehouse.kind!='Warehouse' or warehouse.status!='active'):
            raise serializers.ValidationError({'warehouse':'Select an active warehouse for this branch.'})
        virtual=attrs.get('isVirtual',getattr(self.instance,'isVirtual',False))
        targets=attrs.get('physicalBranches',list(self.instance.physicalBranches.all()) if self.instance else [])
        if virtual and kind!='Branch':raise serializers.ValidationError('Only branches can be virtual.')
        if any(t.kind!='Branch' or t.isVirtual or t.status!='active' or (self.instance and t.pk==self.instance.pk) for t in targets):raise serializers.ValidationError('Choose distinct active physical branches.')
        if virtual and not targets:raise serializers.ValidationError('Select the physical branches for this virtual branch.')
        if virtual and self.instance and m.Stock.objects.filter(location=self.instance).exists():raise serializers.ValidationError('A location with existing stock cannot become virtual.')
        if kind=='Branch' and not virtual and not warehouse and (not self.instance or 'warehouse' in attrs):
            raise serializers.ValidationError({'warehouse':'Select the branch warehouse.'})
        return attrs
    rawMaterialValue=serializers.SerializerMethodField()
    finishedStockValue=serializers.SerializerMethodField()
    todaySales=serializers.SerializerMethodField()
    @extend_schema_field(serializers.JSONField())
    def get_rawMaterialValue(self,o):
        from .services import scoped_stocks
        return sum(s.quantity*s.material.currentCost for s in scoped_stocks(self.context['request'].user).filter(location=o,material__isnull=False).select_related('material'))
    @extend_schema_field(serializers.JSONField())
    def get_finishedStockValue(self,o):
        from .services import scoped_stocks
        return sum(s.quantity*s.variant.costPrice for s in scoped_stocks(self.context['request'].user).filter(location=o,variant__isnull=False).select_related('variant'))
    @extend_schema_field(serializers.JSONField())
    def get_todaySales(self,o):
        from django.utils.timezone import localdate
        from .reports import invoice_scope
        return invoice_scope(self.context['request'].user).filter(branch=o,date=localdate()).aggregate(n=Sum('total'))['n'] or ZERO
    class Meta(TenantSerializer.Meta): model=m.Location;read_only_fields=['kind']

class SupplierSerializer(TenantSerializer):
    contact=serializers.CharField(source="contactPerson",required=False,allow_blank=True)
    code=serializers.CharField(required=False,allow_blank=True)
    outstanding=serializers.SerializerMethodField()
    lastPurchase=serializers.SerializerMethodField()
    @extend_schema_field(serializers.JSONField())
    def get_outstanding(self,o):
        bills=o.bill_set.all();total=sum(b.amount-b.paid for b in bills)
        returns=o.purchasereturn_set.aggregate(n=Sum('totalAmount'))['n'] or ZERO
        adjustments=o.balanceadjustment_set.aggregate(n=Sum('amount'))['n'] or ZERO
        return max(ZERO,total-returns+adjustments)
    @extend_schema_field(serializers.JSONField())
    def get_lastPurchase(self,o):
        p=o.purchaseorder_set.order_by('-orderDate').first();return p.orderDate if p else None
    class Meta(TenantSerializer.Meta): model=m.Supplier

class CustomerSerializer(TenantSerializer):
    outstanding=serializers.SerializerMethodField()
    totalPurchases=serializers.SerializerMethodField()
    lastVisit=serializers.SerializerMethodField()
    @extend_schema_field(serializers.JSONField())
    def get_outstanding(self,o):
        invoices=o.invoice_set.all();total=sum(max(ZERO,i.total-i.paid-(m.SalesReturn.objects.filter(line__invoice=i).aggregate(n=Sum('refundAmount'))['n'] or ZERO)) for i in invoices)
        adj=o.balanceadjustment_set.aggregate(n=Sum('amount'))['n'] or ZERO
        return max(ZERO,total+adj)
    @extend_schema_field(serializers.JSONField())
    def get_totalPurchases(self,o): return o.invoice_set.aggregate(n=Sum('total'))['n'] or ZERO
    @extend_schema_field(serializers.JSONField())
    def get_lastVisit(self,o):
        i=o.invoice_set.order_by('-date').first();return i.date if i else None
    class Meta(TenantSerializer.Meta): model=m.Customer

class MaterialSubcategorySerializer(TenantSerializer):
    def validate(self,attrs):
        attrs=super().validate(attrs)
        from .category_utils import category_role
        parent=attrs.get('parent',getattr(self.instance,'parent',None))
        name=attrs.get('name',getattr(self.instance,'name','')).strip()
        unit=attrs.get('unit',getattr(self.instance,'unit',None))
        if not name: raise serializers.ValidationError({'name':'Enter a subcategory name.'})
        if not parent or parent.status!='active': raise serializers.ValidationError({'parent':'Select an active category.'})
        role=category_role(name)
        if role not in ('Perfume Oil','Solvent'): role=category_role(parent.name)
        if (role in ('Perfume Oil','Solvent') and unit!='ml') or (role=='Packaging' and unit!='pcs'):
            raise serializers.ValidationError({'unit':'Oil and solvent use ml; packaging uses pcs for production compatibility.'})
        qs=m.MaterialSubcategory.objects.filter(parent=parent,name__iexact=name)
        if self.instance:
            qs=qs.exclude(pk=self.instance.pk)
            if self.instance.materials.exists() and (parent!=self.instance.parent or unit!=self.instance.unit or name!=self.instance.name):
                raise serializers.ValidationError('A subcategory in use cannot change parent, name or unit.')
        if qs.exists(): raise serializers.ValidationError({'name':'Subcategory already exists in this category.'})
        attrs['name']=name
        return attrs
    class Meta(TenantSerializer.Meta): model=m.MaterialSubcategory

class MaterialCategorySerializer(TenantSerializer):
    subcategories=MaterialSubcategorySerializer(many=True,read_only=True)
    materialCount=serializers.SerializerMethodField()
    @extend_schema_field(serializers.IntegerField())
    def get_materialCount(self,o): return o.materials.count()
    def validate(self,attrs):
        attrs=super().validate(attrs)
        name=attrs.get('name',getattr(self.instance,'name','')).strip()
        if not name: raise serializers.ValidationError({'name':'Enter a category name.'})
        qs=m.MaterialCategory.objects.filter(organization=self.context['request'].user.organization,name__iexact=name)
        if self.instance: qs=qs.exclude(pk=self.instance.pk)
        if qs.exists(): raise serializers.ValidationError({'name':'Category name already exists.'})
        attrs['name']=name
        return attrs
    class Meta(TenantSerializer.Meta): model=m.MaterialCategory

class OpeningStockSerializer(serializers.Serializer):
    locationId=serializers.CharField()
    quantity=serializers.DecimalField(max_digits=18,decimal_places=4,min_value=Decimal('0'))

class MaterialSerializer(TenantSerializer):
    initialQty=serializers.SerializerMethodField()
    @extend_schema_field(serializers.DecimalField(max_digits=18,decimal_places=4))
    def get_initialQty(self, obj):
        # Opening stock is historical; do not substitute current stock.
        return m.Movement.objects.filter(
            organization=obj.organization,stock__material=obj,
            transaction='OPENING_STOCK',delta__gt=0
        ).aggregate(total=Sum('delta'))['total'] or ZERO
    openingStocks=OpeningStockSerializer(many=True,write_only=True,required=False)
    def create(self,validated_data):
        from . import services
        from django.db import transaction
        rows=validated_data.pop('openingStocks',[])
        with transaction.atomic():
            material=super().create(validated_data)
            for row in rows:
                if row['quantity']:
                    loc=services.location(self.context['request'].user,row['locationId'])
                    services.post_stock(self.context['request'].user,loc,material,row['quantity'],'OPENING_STOCK',material.code,'Opening quantity on material creation')
            return material
    category=serializers.CharField(required=False)
    unit=serializers.ChoiceField(choices=['ml','pcs','g','kg','L'],required=False)
    ingredientActive=serializers.SerializerMethodField()
    def get_ingredientActive(self,o):
        from .category_utils import active_ingredient
        return active_ingredient(o)
    categoryType=serializers.SerializerMethodField()
    @extend_schema_field(serializers.CharField())
    def get_categoryType(self,o):
        from .category_utils import material_type,packaging_type
        return material_type(o)
    def validate(self,attrs):
        attrs=super().validate(attrs)
        if 'fragrancePrices' in attrs:
            from .pricing import prices
            attrs['fragrancePrices']=prices(attrs['fragrancePrices'])
        from .category_utils import LEGACY_TYPES
        user=self.context['request'].user
        if 'openingStocks' in attrs:
            from . import services
            if self.instance: raise serializers.ValidationError({'openingStocks':'Opening quantities can only be set on creation. Use stock adjustments for existing materials.'})
            seen=set()
            for row in attrs['openingStocks']:
                loc=services.location(user,row['locationId'])
                if loc.isVirtual: raise serializers.ValidationError({'openingStocks':'Choose a physical stock location.'})
                if loc.pk in seen: raise serializers.ValidationError({'openingStocks':'Each location may appear only once.'})
                seen.add(loc.pk)
        category=attrs.get('categoryRef',getattr(self.instance,'categoryRef',None))
        if 'category' in attrs and ('categoryRef' not in attrs):
            category=m.MaterialCategory.objects.filter(organization=user.organization,name=attrs['category']).first()
        from .category_utils import classification
        sub=attrs.get('subcategoryRef',getattr(self.instance,'subcategoryRef',None))
        kind=classification(category,sub) if sub or not self.instance or (category and category.pk!=self.instance.categoryRef_id) else self.instance.materialType
        attrs['materialType']=kind
        if not sub and (not self.instance or self.instance.subcategoryRef_id or (category and category.pk!=self.instance.categoryRef_id)):
            raise serializers.ValidationError({'subcategoryRef':'Select a subcategory.'})
        if sub and (sub.parent_id!=getattr(category,'pk',None) or (sub.status!='active' and (not self.instance or sub.pk!=self.instance.subcategoryRef_id))):
            raise serializers.ValidationError({'subcategoryRef':'Select an active subcategory of the selected category.'})
        unit=sub.unit if sub else attrs.get('unit',getattr(self.instance,'unit','ml'))
        if kind in {'Perfume Oil','Solvent'} and unit!='ml': raise serializers.ValidationError({'unit':'Oil and solvent must use ml.'})
        if kind=='Packaging' and unit!='pcs': raise serializers.ValidationError({'unit':'Packaging must use pcs.'})
        if attrs.get('fragrancePrices') and kind!='Perfume Oil': raise serializers.ValidationError('Fragrance selling prices apply only to oil materials.')
        if not category: raise serializers.ValidationError({'categoryRef':'Select a registered category.'})
        if unit=='pcs' and any(row['quantity'] != row['quantity'].to_integral_value() for row in attrs.get('openingStocks',[])):
            raise serializers.ValidationError({'openingStocks':'Piece quantities must be whole numbers.'})
        if category.status!='active' and (not self.instance or category.pk!=self.instance.categoryRef_id): raise serializers.ValidationError('Choose an active category.')
        legacy=attrs.get('category','')
        subtype=attrs.get('packagingType',getattr(self.instance,'packagingType','') if self.instance else legacy if legacy in {'Bottle','Pump','Cap','Label','Dip Tube'} else '')
        if kind=='Packaging':
            if sub: subtype={'bottle':'Bottle','pump':'Pump','atomizer':'Pump','cap':'Cap','label':'Label','dip tube':'Dip Tube'}.get(sub.name.strip().casefold(),'Other')
            if not subtype and (not self.instance or 'packagingType' in attrs or (self.instance and self.instance.materialType!=kind)):raise serializers.ValidationError({'packagingType':'Select Bottle, Pump, Cap, Label, Dip Tube or Other packaging.'})
            if unit!='pcs':raise serializers.ValidationError('Packaging categories must use pcs.')
        elif subtype:raise serializers.ValidationError({'packagingType':'Packaging subtype applies only to Packaging materials.'})
        if self.instance and subtype!=self.instance.packagingType:
            for saved_product in m.Product.objects.filter(organization=user.organization,directBlend=True).exclude(packagingRecipe=[]).only('packagingRecipe'):
                for component in saved_product.packagingRecipe:
                    expected={'Pump / atomizer':'Pump','Dip tube':'Dip Tube'}.get(component['role'],component['role'])
                    if component['materialId']==self.instance.pk and subtype!=expected:raise serializers.ValidationError({'packagingType':f'This material is saved as {expected} in a product packaging set.'})
            fields=['bottleMaterialRef','pumpMaterialRef','capMaterialRef','labelMaterialRef','dipTubeMaterialRef'];roles=['Bottle','Pump','Cap','Label','Dip Tube']
            for field,role in zip(fields,roles):
                if m.BottleSize.objects.filter(**{field:self.instance}).exists() and subtype!=role:raise serializers.ValidationError({'packagingType':f'This material is linked as {role} in Bottle Setup.'})
        attrs['packagingType']=subtype
        attrs.update(categoryRef=category,category=category.name,unit=unit)
        if self.instance and (unit!=self.instance.unit or kind!=material_type(self.instance)):
            if m.Movement.objects.filter(stock__material=self.instance).exists() or m.FormulaLine.objects.filter(material=self.instance).exists() or m.PercentageIngredient.objects.filter(material=self.instance).exists() or m.VariantPackaging.objects.filter(material=self.instance).exists():
                raise serializers.ValidationError('Unit and material role are locked once used in a recipe or stock history. Create a new material for a different unit.')
        return attrs

    availableStock=serializers.SerializerMethodField()
    @extend_schema_field(serializers.JSONField())
    def get_availableStock(self,o):
        from .services import scoped_stocks
        qs=scoped_stocks(self.context['request'].user).filter(material=o)
        loc=self.context['request'].query_params.get('location')
        if loc: qs=qs.filter(location__name=loc)
        return qs.aggregate(n=Sum('quantity'))['n'] or ZERO
    class Meta(TenantSerializer.Meta):
        model=m.Material
        read_only_fields=["materialType", "currentCost", "compatibleBottleSizes"]

class FragranceSerializer(TenantSerializer):
    def validate(self,attrs):
        if 'pricesByType' in attrs:
            from .pricing import bottle_prices
            attrs['pricesByType']=bottle_prices(attrs['pricesByType'],self.context['request'].user.organization)
        attrs=super().validate(attrs)
        oil=attrs.get("perfumeOilId",getattr(self.instance,"perfumeOilId",None))
        from .category_utils import active_ingredient
        if oil and (material_type(oil)!="Perfume Oil" or not active_ingredient(oil)): raise serializers.ValidationError("Choose an active Perfume Oil material measured in ml.")
        return attrs
    class Meta(TenantSerializer.Meta):
        model=m.Fragrance
        read_only_fields=["knots"]
class ConcentrationSerializer(TenantSerializer):
    remainingPercentage=serializers.SerializerMethodField()
    @extend_schema_field(serializers.JSONField())
    def get_remainingPercentage(self,o): return 100-o.oilPercentage
    class Meta(TenantSerializer.Meta): model=m.Concentration
class BottleSizeSerializer(TenantSerializer):
    def validate(self,attrs):
        attrs=super().validate(attrs)
        if self.instance and (m.Variant.objects.filter(bottleSizeId=self.instance).exists() or m.Product.objects.filter(bottleSizeRef=self.instance).exists()) and any(k in attrs and attrs[k]!=getattr(self.instance,k) for k in ['volumeMl','bottleMaterialRef']): raise serializers.ValidationError('Bottle capacity/reference is in use. Create a new bottle size.')
        if 'volumeMl' in attrs:
            attrs['name'] = f"{format(attrs['volumeMl'].normalize(), 'f')} ml"
        refs=[]
        for field in ['bottleMaterialRef','pumpMaterialRef','capMaterialRef','labelMaterialRef','dipTubeMaterialRef']:
            item=attrs.get(field,getattr(self.instance,field,None))
            if not item: continue
            if material_type(item)!='Packaging' or item.unit!='pcs' or item.status!='active': raise serializers.ValidationError({field:'Select active packaging measured in pcs.'})
            role={'bottleMaterialRef':'Bottle','pumpMaterialRef':'Pump','capMaterialRef':'Cap','labelMaterialRef':'Label','dipTubeMaterialRef':'Dip Tube'}[field]
            unchanged=self.instance and getattr(self.instance,field+'_id')==item.pk
            if packaging_type(item)!=role and not (unchanged and not packaging_type(item)):raise serializers.ValidationError({field:f'Select a {role} packaging material.'})
            if item.pk in refs: raise serializers.ValidationError('Bottle, pump, cap and separately stocked dip tube must be distinct materials.')
            refs.append(item.pk)
        mat=attrs.get('bottleMaterialRef',getattr(self.instance,'bottleMaterialRef',None))
        if mat and (material_type(mat)!='Packaging' or mat.unit!='pcs'): raise serializers.ValidationError('Bottle reference must be a Bottle or Packaging inventory material in pcs.')
        return attrs
    class Meta(TenantSerializer.Meta):
        model=m.BottleSize
        read_only_fields=["name", "priceMultiplier", "priceSurcharge"]

class FormulaSerializer(TenantSerializer):
    percentageIngredients=serializers.SerializerMethodField()
    @extend_schema_field(serializers.JSONField())
    def get_percentageIngredients(self,o): return [{"materialId":r.material_id,"name":r.material.name,"type":material_type(r.material),"percentage":r.percentage} for r in o.percentages.select_related("material")]
    ingredients=serializers.SerializerMethodField()
    packaging=serializers.SerializerMethodField()
    def rows(self,o,group): return [{'materialId':l.material_id,'name':l.material.name,'type':material_type(l.material),'qty':l.qty,'unit':l.material.unit,'rate':l.rate,'cost':cash(l.qty*l.rate),'required':l.required} for l in o.lines.filter(group=group).select_related('material')]
    @extend_schema_field(serializers.JSONField())
    def get_ingredients(self,o): return self.rows(o,'ingredients')
    @extend_schema_field(serializers.JSONField())
    def get_packaging(self,o): return self.rows(o,'packaging')
    class Meta(TenantSerializer.Meta): model=m.Formula

class ProductSerializer(TenantSerializer):
    code=serializers.CharField(required=False)
    fragranceName=serializers.CharField(source="fragranceId.name",read_only=True,default="")
    variantsCount=serializers.SerializerMethodField()
    finishedStock=serializers.SerializerMethodField()
    availableStock=serializers.SerializerMethodField()
    def get_availableStock(self,o):
        if o.directBlend:
            from .direct_perfume import producible_stock
            return producible_stock(o,self.context['request'].user)
        return self.get_finishedStock(o)
    @extend_schema_field(serializers.JSONField())
    def get_variantsCount(self,o): return o.variants.count()
    @extend_schema_field(serializers.JSONField())
    def get_finishedStock(self,o):
        from .services import scoped_stocks
        return scoped_stocks(self.context['request'].user).filter(variant__productId=o).aggregate(n=Sum('quantity'))['n'] or ZERO
    class Meta(TenantSerializer.Meta):
        model=m.Product
        read_only_fields=['blendConfig','fragranceFirst','fragranceType','pricingMode','pricingSnapshot','bottleSizeRef','packagingRecipe','directBlend','fillVolumeMl','sellingPrice','minSellingPrice','recipe','recipeRevision']

class VariantSerializer(TenantSerializer):
    percentageRecipe=serializers.BooleanField(source="formulaId.percentageRecipe",read_only=True)
    recipe=serializers.SerializerMethodField()
    packagingItems=serializers.SerializerMethodField()
    estimatedCost=serializers.SerializerMethodField()
    @extend_schema_field(serializers.JSONField())
    def get_recipe(self,o):
        from .workflow import costing
        return costing(o)
    @extend_schema_field(serializers.JSONField())
    def get_estimatedCost(self,o):
        from .workflow import costing
        return costing(o)["totalEstimatedUnitCost"]
    @extend_schema_field(serializers.JSONField())
    def get_packagingItems(self,o): return [{"materialId":r.material_id,"qty":r.qty} for r in o.packaging.all()]
    name=serializers.CharField(required=False,allow_blank=True)
    productName=serializers.CharField(source='productId.name',read_only=True)
    sizeName=serializers.CharField(source='bottleSizeId.name',read_only=True)
    concentrationName=serializers.CharField(source='concentrationId.code',read_only=True)
    fragranceName=serializers.CharField(source='fragranceId.name',read_only=True)
    liquidCost=serializers.SerializerMethodField()
    packagingCost=serializers.SerializerMethodField()
    manufacturingCost=serializers.SerializerMethodField()
    formulaCost=serializers.DecimalField(source="formulaId.estimatedUnitCost",max_digits=16,decimal_places=2,read_only=True)
    @extend_schema_field(serializers.JSONField())
    def get_liquidCost(self,o):
        if o.formulaId.percentageRecipe:
            from .workflow import costing
            c=costing(o);return c['perfumeOilCost']+c['solventCost']
        return sum(l.qty*l.rate for l in o.formulaId.lines.filter(group="ingredients"))
    @extend_schema_field(serializers.JSONField())
    def get_packagingCost(self,o):
        if o.formulaId.percentageRecipe:
            from .workflow import costing
            return costing(o)['packagingCost']
        return sum(l.qty*l.rate for l in o.formulaId.lines.filter(group="packaging"))
    @extend_schema_field(serializers.JSONField())
    def get_manufacturingCost(self,o): return o.additionalCost if o.formulaId.percentageRecipe else o.formulaId.laborCost+o.formulaId.cleaningAllocation+o.formulaId.otherCost
    stock=serializers.SerializerMethodField()
    branchStock=serializers.SerializerMethodField()
    warehouseStock=serializers.SerializerMethodField()
    margin=serializers.SerializerMethodField()
    def stocks(self,o):
        from .services import scoped_stocks
        qs=scoped_stocks(self.context['request'].user).filter(variant=o)
        branch=self.context['request'].query_params.get('branchId')
        loc=self.context['request'].query_params.get('location')
        if branch: qs=qs.filter(location_id=branch)
        if loc: qs=qs.filter(location__name=loc)
        return qs
    @extend_schema_field(serializers.JSONField())
    def get_stock(self,o): return self.stocks(o).aggregate(n=Sum('quantity'))['n'] or ZERO
    @extend_schema_field(serializers.JSONField())
    def get_branchStock(self,o): return {s.location_id:s.quantity for s in self.stocks(o).filter(location__kind='Branch')}
    @extend_schema_field(serializers.JSONField())
    def get_warehouseStock(self,o): return {s.location_id:s.quantity for s in self.stocks(o).filter(location__kind='Warehouse')}
    @extend_schema_field(serializers.JSONField())
    def get_margin(self,o): return f'{(o.sellingPrice-o.costPrice)/o.sellingPrice*100:.1f}%' if o.sellingPrice else '0.0%'
    def validate(self,attrs):
        attrs=super().validate(attrs)
        def value(k): return attrs.get(k,getattr(self.instance,k,None))
        if self.instance and m.Movement.objects.filter(stock__variant=self.instance).exists() and any(k in attrs and attrs[k]!=getattr(self.instance,k) for k in ['formulaId','fragranceId','bottleSizeId','concentrationId']): raise serializers.ValidationError('Recipe basis is locked after stock history. Create a new SKU.')
        f=value('formulaId')
        if f and f.percentageRecipe:
            raise serializers.ValidationError('Manage percentage recipe variants through the unified Product form.')
        if f and any(value(k).pk!=getattr(f,k+'_id') for k in (['fragranceId'] if f.percentageRecipe else ['fragranceId','bottleSizeId','concentrationId'])): raise serializers.ValidationError('Formula basis must match the variant fragrance, size and concentration.')
        if value('sellingPrice') is not None and value('minSellingPrice') is not None and value('minSellingPrice')>value('sellingPrice'): raise serializers.ValidationError('Minimum selling price exceeds selling price.')
        return attrs
    class Meta(TenantSerializer.Meta): model=m.Variant;read_only_fields=['costPrice']

class BatchSerializer(TenantSerializer):
    productVariantId=serializers.CharField(source='variant_id',read_only=True)
    productSku=serializers.CharField(source='variant.sku',read_only=True)
    productName=serializers.CharField(source='variant.name',read_only=True)
    warehouseName=serializers.CharField(source='warehouse.name',read_only=True)
    standardConsumption=serializers.SerializerMethodField()
    @extend_schema_field(serializers.JSONField())
    def get_standardConsumption(self,o): return [{'materialId':l.material_id,'name':l.material.name,'unit':l.material.unit,'standard':l.standard,'actual':l.actual,'rate':l.rate,'variance':l.actual-l.standard,'varianceCost':(l.actual-l.standard)*l.rate} for l in o.consumptions.select_related('material')]
    class Meta(TenantSerializer.Meta): model=m.Batch

class TransferSerializer(TenantSerializer):
    sourceName=serializers.CharField(source='source.name',read_only=True)
    destName=serializers.CharField(source='destination.name',read_only=True)
    sourceType=serializers.CharField(source='source.kind',read_only=True)
    destType=serializers.CharField(source='destination.kind',read_only=True)
    requestedBy=serializers.CharField(source='requestedBy.username',read_only=True)
    approvedBy=serializers.CharField(source='approvedBy.username',read_only=True,default='')
    dispatchedBy=serializers.CharField(source='dispatchedBy.username',read_only=True,default='')
    receivedBy=serializers.CharField(source='receivedBy.username',read_only=True,default='')
    lifecycle=serializers.SerializerMethodField()
    @extend_schema_field(serializers.JSONField())
    def get_lifecycle(self,o): return {'requestedAt':o.created_at,'approvedAt':o.approvedAt,'dispatchedAt':o.dispatchedAt,'receivedAt':o.receivedAt}
    items=serializers.SerializerMethodField()
    itemsCount=serializers.SerializerMethodField()
    @extend_schema_field(serializers.JSONField())
    def get_itemsCount(self,o): return o.lines.count()
    @extend_schema_field(serializers.JSONField())
    def get_items(self,o): return [{'id':l.pk,'itemId':(l.material or l.variant).pk,'itemType':'Raw Material' if l.material_id else 'Finished Product','itemName':(l.material or l.variant).name,'sku':l.material.code if l.material_id else l.variant.sku,'availableQty':m.Stock.objects.filter(location=o.source,material=l.material,variant=l.variant).aggregate(n=Sum('quantity'))['n'] or ZERO,'requestedQty':l.requestedQty,'dispatchedQty':l.dispatchedQty,'receivedQty':l.receivedQty,'damagedQty':l.damagedQty,'unit':l.material.unit if l.material_id else 'pcs'} for l in o.lines.select_related('material','variant')]
    class Meta(TenantSerializer.Meta): model=m.Transfer

class PurchaseOrderSerializer(TenantSerializer):
    supplierName=serializers.CharField(source='supplier.name',read_only=True)
    warehouseName=serializers.CharField(source='warehouse.name',read_only=True)
    items=serializers.SerializerMethodField()
    @extend_schema_field(serializers.JSONField())
    def get_items(self,o): return [{'id':l.pk,'materialId':l.material_id,'material':l.material.name,'unit':l.material.unit,'qty':l.qty,'orderedQty':l.qty,'rate':l.rate,'discount':l.discount,'tax':l.tax,'total':cash(l.qty*l.rate-l.discount+l.tax),'prevReceived':l.received} for l in o.lines.select_related('material')]
    class Meta(TenantSerializer.Meta): model=m.PurchaseOrder

class ReceiptSerializer(TenantSerializer):
    poNumber=serializers.CharField(source='order.poNumber',read_only=True)
    supplierName=serializers.CharField(source='order.supplier.name',read_only=True)
    warehouseName=serializers.CharField(source='order.warehouse.name',read_only=True)
    items=serializers.SerializerMethodField()
    @extend_schema_field(serializers.JSONField())
    def get_items(self,o): return [{'materialId':l.orderLine.material_id,'material':l.orderLine.material.name,'orderedQty':l.orderLine.qty,'currentReceived':l.currentReceived,'acceptedQty':l.acceptedQty,'rejectedQty':l.rejectedQty,'unitCost':l.unitCost,'total':cash(l.acceptedQty*l.unitCost)} for l in o.lines.select_related('orderLine__material')]
    class Meta(TenantSerializer.Meta): model=m.Receipt

class BillSerializer(TenantSerializer):
    supplierName=serializers.CharField(source='supplier.name',read_only=True)
    balance=serializers.SerializerMethodField()
    status=serializers.SerializerMethodField()
    @extend_schema_field(serializers.JSONField())
    def get_balance(self,o):
        from .services import bill_credit
        return max(ZERO,o.amount-o.paid-bill_credit(o))
    @extend_schema_field(serializers.JSONField())
    def get_status(self,o): return 'Paid / Credited' if self.get_balance(o)==0 else 'Partially Paid' if o.paid else 'Unpaid'
    def validate(self,attrs):
        attrs=super().validate(attrs)
        amount=attrs.get('amount',getattr(self.instance,'amount',ZERO));paid=attrs.get('paid',getattr(self.instance,'paid',ZERO))
        if amount<=0 or paid>amount: raise serializers.ValidationError('Bill amount must be positive and paid cannot exceed amount.')
        if attrs.get('dueDate',getattr(self.instance,'dueDate',None))<attrs.get('date',getattr(self.instance,'date',None)): raise serializers.ValidationError('Due date precedes bill date.')
        return attrs
    class Meta(TenantSerializer.Meta): model=m.Bill

class PurchaseReturnSerializer(TenantSerializer):
    supplierName=serializers.CharField(source='supplier.name',read_only=True)
    warehouseName=serializers.CharField(source='warehouse.name',read_only=True)
    material=serializers.CharField(source='material.name',read_only=True)
    unit=serializers.CharField(source='material.unit',read_only=True)
    inventoryImpact=serializers.SerializerMethodField()
    @extend_schema_field(serializers.JSONField())
    def get_inventoryImpact(self,o): return f'Inventory Deducted (-{o.qty} {o.material.unit} {o.material.name} from {o.warehouse.name})'
    class Meta(TenantSerializer.Meta): model=m.PurchaseReturn

class InvoiceSerializer(TenantSerializer):
    taxTotal=serializers.DecimalField(source="tax",max_digits=18,decimal_places=4,read_only=True)
    paymentStatus=serializers.CharField(source="status",read_only=True)
    qty=serializers.SerializerMethodField()
    @extend_schema_field(serializers.JSONField())
    def get_qty(self,o): return sum(l.qty for l in o.lines.all())
    branchName=serializers.CharField(source='branch.name',read_only=True)
    salesperson=serializers.CharField(source='salesperson.username',read_only=True)
    items=serializers.SerializerMethodField()
    balance=serializers.SerializerMethodField()
    @extend_schema_field(serializers.JSONField())
    def get_items(self,o): return [{'id':l.pk,'productName':l.productName,'sku':l.sku,'qty':l.qty,'rate':l.rate,'discount':l.discount,'total':l.total,'costSnapshot':l.costSnapshot,'returnedQty':l.returned,'productId':l.product_id,'recipeSnapshot':l.recipeSnapshot,'packagingSnapshot':l.packagingSnapshot,'pricingSnapshot':l.pricingSnapshot} for l in o.lines.all()]
    @extend_schema_field(serializers.JSONField())
    def get_balance(self,o): return max(ZERO,o.total-o.paid-(m.SalesReturn.objects.filter(line__invoice=o).aggregate(n=Sum('refundAmount'))['n'] or ZERO))
    class Meta(TenantSerializer.Meta): model=m.Invoice;read_only_fields=['checkoutKey','checkoutFingerprint']

class SalesReturnSerializer(TenantSerializer):
    invoiceNumber=serializers.CharField(source='line.invoice.invoiceNumber',read_only=True)
    productName=serializers.CharField(source='line.productName',read_only=True)
    customerName=serializers.CharField(source='line.invoice.customerName',read_only=True)
    class Meta(TenantSerializer.Meta): model=m.SalesReturn

class MovementSerializer(TenantSerializer):
    item=serializers.SerializerMethodField()
    location=serializers.CharField(source='stock.location.name',read_only=True)
    direction=serializers.SerializerMethodField()
    quantity=serializers.SerializerMethodField()
    user=serializers.CharField(source='user.username',read_only=True)
    @extend_schema_field(serializers.JSONField())
    def get_item(self,o): return (o.stock.material or o.stock.variant).name
    @extend_schema_field(serializers.JSONField())
    def get_direction(self,o): return 'IN' if o.delta>=0 else 'OUT'
    @extend_schema_field(serializers.JSONField())
    def get_quantity(self,o): return f'{abs(o.delta)} {o.stock.material.unit if o.stock.material_id else "pcs"}'
    class Meta(TenantSerializer.Meta): model=m.Movement

class WastageSerializer(TenantSerializer):
    item=serializers.SerializerMethodField()
    location=serializers.CharField(source='stock.location.name',read_only=True)
    unit=serializers.SerializerMethodField()
    user=serializers.CharField(source='user.username',read_only=True)
    @extend_schema_field(serializers.JSONField())
    def get_item(self,o): return (o.stock.material or o.stock.variant).name
    @extend_schema_field(serializers.JSONField())
    def get_unit(self,o): return o.stock.material.unit if o.stock.material_id else 'pcs'
    class Meta(TenantSerializer.Meta): model=m.Wastage

class ExpenseSerializer(TenantSerializer):
    createdBy=serializers.CharField(source='createdBy.username',read_only=True,default='')
    branchOrWarehouse=serializers.CharField(source="location",required=False,allow_blank=True)
    def validate(self,attrs):
        attrs=super().validate(attrs)
        if attrs.get('amount',getattr(self.instance,'amount',ZERO))<=0: raise serializers.ValidationError({'amount':'A positive expense amount is required.'})
        return attrs
    class Meta(TenantSerializer.Meta): model=m.Expense
class LedgerSerializer(TenantSerializer):
    def validate(self,attrs):
        attrs=super().validate(attrs)
        if attrs.get('amount',getattr(self.instance,'amount',ZERO))<=0: raise serializers.ValidationError({'amount':'Enter a positive amount.'})
        return attrs

    balance=serializers.SerializerMethodField()
    @extend_schema_field(serializers.JSONField())
    def get_balance(self,o):
        qs=m.LedgerEntry.objects.filter(organization=o.organization,account=o.account,created_at__lte=o.created_at)
        return sum(e.amount if e.type=='Inflow' else -e.amount for e in qs)
    class Meta(TenantSerializer.Meta): model=m.LedgerEntry;read_only_fields=['source','sourceId','status']
