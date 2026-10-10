"""Explicit demo catalog import, separate from real transactions and startup."""
import json
from pathlib import Path
from decimal import Decimal
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.conf import settings
from django.db import transaction
from apps.erp import models as m, services as svc
class Command(BaseCommand):
 help='Populate catalog and opening stock in an EMPTY organization, only when explicitly requested.'
 def add_arguments(self,p): p.add_argument('--username',required=True)
 @transaction.atomic
 def handle(self,*args,**opts):
  if not settings.DEBUG: raise CommandError('Demo data cannot be loaded with DEBUG=False.')
  try: u=get_user_model().objects.get(username=opts['username'],is_superuser=True)
  except get_user_model().DoesNotExist: raise CommandError('An existing superuser is required.')
  if not u.organization_id: raise CommandError('Run bootstrap_business first.')
  if m.Location.objects.filter(organization=u.organization).exists(): raise CommandError('Organization already contains locations. Demo seed will not overwrite or duplicate data.')
  data=json.loads((Path(__file__).resolve().parents[2]/'demo_catalog.json').read_text())
  refs={}
  def create(model,row,**extra):
   names={f.name for f in model._meta.fields}-{'id','organization','created_at','updated_at'}
   row={**row,**({'contactPerson':row.get('contact','')} if model==m.Supplier else {})}
   values={k:v for k,v in row.items() if k in names and not isinstance(model._meta.get_field(k),m.models.ForeignKey)}
   obj=model.objects.create(organization=u.organization,**values,**extra);refs[row['id']]=obj;return obj
  for key,kind in [('warehouses','Warehouse'),('branches','Branch')]:
   for row in data[key]: create(m.Location,row,kind=kind)
  for row in data['suppliers']: create(m.Supplier,row)
  for row in data['rawMaterials']:
   sup=m.Supplier.objects.filter(organization=u.organization,name=row.get('supplierName')).first()
   obj=create(m.Material,row,supplier=sup)
   svc.post_stock(u,refs['wh-1'],obj,Decimal(str(row['availableStock'])),'DEMO_OPENING','DEMO-SEED','Explicit demo opening inventory')
  for row in data['fragrances']: create(m.Fragrance,row,perfumeOilId=refs[row['perfumeOilId']])
  for row in data['concentrations']: create(m.Concentration,row)
  for row in data['bottleSizes']: create(m.BottleSize,row,bottleMaterialRef=refs[row['bottleMaterialRef']])
  for row in data['products']: create(m.Product,{**row,'code':row.get('code',row['id'].upper())},fragranceId=refs[row['fragranceId']])
  for row in data['customers']: create(m.Customer,row)
  # One consistent formula and variant per catalog product, calculated using actual seed material prices.
  for row in data['products']:
   f=svc.save_formula(u,{'fragranceId':refs[row['fragranceId']].pk,'concentrationId':refs['conc-2'].pk,'bottleSizeId':refs['bs-2'].pk,'laborCost':10,'cleaningAllocation':2.5,'otherCost':3})
   product=refs[row['id']]
   v=m.Variant.objects.create(organization=u.organization,name=f'{product.name} 50 ml EDP',productId=product,fragranceId=f.fragranceId,concentrationId=f.concentrationId,bottleSizeId=f.bottleSizeId,formulaId=f,sku=f'{f.fragranceId.code}-50-EDP',costPrice=f.estimatedUnitCost,sellingPrice=599,minSellingPrice=500,mrp=749)
   for loc,qty in [(refs['wh-1'],40),(refs['br-1'],20),(refs['br-2'],15)]: svc.post_stock(u,loc,v,Decimal(qty),'DEMO_OPENING','DEMO-SEED','Explicit demo opening finished goods')
  from apps.erp.category_utils import register_existing_categories
  register_existing_categories(u.organization)
  u.branch=refs['br-1'];u.warehouse=refs['wh-1'];u.save()
  self.stdout.write(self.style.SUCCESS('Demo catalogs and opening stocks created. No mock invoices or synthetic report totals were imported.'))
