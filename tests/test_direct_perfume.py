from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from apps.accounts.models import Organization
from apps.erp import models as m

class DirectPerfumeTests(TestCase):
 def setUp(self):
  self.org=Organization.objects.create(name='Blend shop')
  self.br=m.Location.objects.create(organization=self.org,name='Branch 1',code='BR01',kind='Branch')
  self.other=m.Location.objects.create(organization=self.org,name='Branch 2',code='BR02',kind='Branch')
  self.user=get_user_model().objects.create_user(username='blend-owner',organization=self.org,role='owner',branch=self.br)
  self.api=APIClient();self.api.force_authenticate(self.user);self.ingredients=[]
  for name,kind,code in [('Oil A','Perfume Oil','A'),('Oil B','Perfume Oil','B'),('Solvent','Solvent','S')]:
   mat=m.Material.objects.create(organization=self.org,name=name,code=code,category=kind,unit='ml',currentCost=1,fragrancePrices={'PARFUM':'500','EDP':'500','EDT':'500','EDC':'500','EAU_FRAICHE':'500'} if kind=='Perfume Oil' else {});self.ingredients.append(mat)
   for branch in [self.br,self.other]:m.Stock.objects.create(organization=self.org,location=branch,material=mat,quantity=1000)
  self.packaging=[]
  for index,name in enumerate(['Bottle','Cap','Pump','Label']):
   material=m.Material.objects.create(organization=self.org,name=name,code='PKG'+str(index),category='Packaging',unit='pcs',packagingType=name);self.packaging.append(material)
   for branch in [self.br,self.other]:m.Stock.objects.create(organization=self.org,location=branch,material=material,quantity=100)
  self.bottle=m.BottleSize.objects.create(organization=self.org,name='100 ml set',volumeMl=100,bottleMaterialRef=self.packaging[0],capMaterialRef=self.packaging[1],pumpMaterialRef=self.packaging[2],labelMaterialRef=self.packaging[3])
  self.body=dict(fragranceType='PARFUM',pricingMode='override',bottleSizeId=self.bottle.pk,name='Custom Perfume',fillVolumeMl=100,sellingPrice=500,recipe=[dict(materialId=x.pk,percentage=p) for x,p in zip(self.ingredients,[20,10,70])])
 def product(self,**kw):
  r=self.api.post('/api/v1/perfume-products/',{**self.body,**kw},format='json');self.assertEqual(r.status_code,201,r.data);return r.data
 def checkout(self,product,**kw):
  data=dict(branchId=self.br.pk,paymentMethod='Cash',checkoutKey='blend-test-key',cart=[dict(productId=product['id'],recipeRevision=product['recipeRevision'],pricingToken=product.get('pricingToken'),qty=2)])
  return self.api.post('/api/v1/sales/pos/checkout/',{**data,**kw},format='json')
 def balance(self,mat,branch=None):return m.Stock.objects.get(material=mat,location=branch or self.br).quantity
 def test_exact_deduction_snapshot_and_idempotency(self):
  p=self.product();r=self.checkout(p);self.assertEqual(r.status_code,201,r.data)
  self.assertEqual([self.balance(x) for x in self.ingredients],[960,980,860]);self.assertEqual([self.balance(x,self.other) for x in self.ingredients],[1000]*3)
  line=m.InvoiceLine.objects.get();self.assertIsNone(line.variant_id);self.assertEqual(line.product_id,p['id']);self.assertEqual([Decimal(x['quantity']) for x in line.recipeSnapshot],[40,20,140])
  again=self.checkout(p);self.assertIn(again.status_code,[200,201],again.data);self.assertEqual(m.Invoice.objects.count(),1);self.assertEqual(self.balance(self.ingredients[0]),960)
  from apps.erp.reports import build_report
  self.assertEqual(build_report(self.user,{})['salesSummary']['unitsSold'],2)
 def test_invalid_recipe_and_duplicates(self):
  for recipe in [[dict(materialId=x.pk,percentage=p) for x,p in zip(self.ingredients,[20,10,69])], [dict(materialId=self.ingredients[0].pk,percentage=20),dict(materialId=self.ingredients[0].pk,percentage=80)]]:
   r=self.api.post('/api/v1/perfume-products/',{**self.body,'recipe':recipe},format='json');self.assertEqual(r.status_code,400,r.data)
  self.assertEqual(m.Product.objects.count(),0)
 def test_insufficient_stock_rolls_back_entire_sale(self):
  p=self.product();m.Stock.objects.filter(location=self.br,material=self.ingredients[0]).update(quantity=25)
  r=self.checkout(p);self.assertEqual(r.status_code,400,r.data);self.assertIn('available: 25',str(r.data));self.assertEqual(m.Invoice.objects.count(),0)
  self.assertEqual([self.balance(x) for x in self.ingredients],[25,1000,1000]);self.assertEqual(m.Movement.objects.count(),0)
 def test_shared_ingredient_validation_aggregates_cart(self):
  p=self.product();q=self.product(name='Second perfume');m.Stock.objects.filter(location=self.br,material=self.ingredients[0]).update(quantity=60)
  r=self.checkout(p,cart=[dict(productId=x['id'],recipeRevision=1,pricingToken=x.get('pricingToken'),qty=2) for x in [p,q]])
  self.assertEqual(r.status_code,400,r.data);self.assertIn('80.0000',str(r.data));self.assertEqual(m.Invoice.objects.count(),0)
 def test_virtual_requires_explicit_linked_physical_branch(self):
  virtual=m.Location.objects.create(organization=self.org,name='Branch 3',code='BR03',kind='Branch',isVirtual=True);virtual.physicalBranches.set([self.br,self.other])
  p=self.product();r=self.checkout(p,branchId=virtual.pk);self.assertEqual(r.status_code,400,r.data)
  r=self.checkout(p,branchId=virtual.pk,physicalBranchId=self.other.pk);self.assertEqual(r.status_code,201,r.data);self.assertEqual(m.Invoice.objects.get().branch_id,self.other.pk)
  self.assertEqual(self.balance(self.ingredients[0]),1000);self.assertEqual(self.balance(self.ingredients[0],self.other),960)
 def test_changed_recipe_blocks_stale_cart_and_preserves_invoice(self):
  p=self.product();self.assertEqual(self.checkout(p).status_code,201);snapshot=m.InvoiceLine.objects.get().recipeSnapshot
  r=self.api.patch('/api/v1/perfume-products/'+p['id']+'/',{**self.body,'recipeRevision':1,'name':'Updated perfume'},format='json');self.assertEqual(r.status_code,200,r.data)
  self.assertEqual(self.checkout(p,checkoutKey='stale-key').status_code,400);self.assertEqual(m.InvoiceLine.objects.get().recipeSnapshot,snapshot)
 def test_quote_does_not_consume_stock_and_short_cash_rolls_back(self):
  p=self.product();body=dict(branchId=self.br.pk,cart=[dict(productId=p['id'],recipeRevision=1,pricingToken=p.get('pricingToken'),qty=2)])
  r=self.api.post('/api/v1/perfume-quote/',body,format='json');self.assertEqual(r.status_code,200,r.data);self.assertEqual(r.data['total'],1000)
  self.assertEqual(self.checkout(p,tendered=500).status_code,400);self.assertEqual(m.Invoice.objects.count(),0);self.assertEqual(self.balance(self.ingredients[0]),1000)

 def test_foreign_or_wrong_unit_ingredient_rejected(self):
  other=Organization.objects.create(name='Foreign')
  material=m.Material.objects.create(organization=other,name='Foreign oil',code='X',category='Perfume Oil',unit='ml')
  body={**self.body,'recipe':[{'materialId':material.pk,'percentage':20},{'materialId':self.ingredients[2].pk,'percentage':80}]}
  self.assertEqual(self.api.post('/api/v1/perfume-products/',body,format='json').status_code,400)
  self.ingredients[0].unit='pcs';self.ingredients[0].save()
  self.assertEqual(self.api.post('/api/v1/perfume-products/',self.body,format='json').status_code,400)
 def test_duplicate_product_name_prevented(self):
  self.product()
  self.assertEqual(self.api.post('/api/v1/perfume-products/',{**self.body,'name':'custom perfume'},format='json').status_code,400)
 def test_cashier_cannot_use_another_branch(self):
  p=self.product();self.user.role='cashier';self.user.save()
  r=self.checkout(p,branchId=self.other.pk);self.assertEqual(r.status_code,403,r.data)
  self.assertEqual(m.Invoice.objects.count(),0)
 def test_refund_does_not_unmix_consumed_ingredients(self):
  p=self.product();sale=self.checkout(p);self.assertEqual(sale.status_code,201,sale.data)
  invoice=sale.data['invoice'];line=m.InvoiceLine.objects.get()
  r=self.api.post('/api/v1/sales/returns/',dict(invoiceNumber=invoice['invoiceNumber'],sku=line.sku,qty=1,condition='Sellable',reason='Customer return',refundMethod='Cash'),format='json')
  self.assertEqual(r.status_code,201,r.data);self.assertEqual(self.balance(self.ingredients[0]),960)
  from apps.erp.reports import build_report
  self.assertEqual(build_report(self.user,{})['salesSummary']['cogs'],200)
 def test_product_fragrance_and_bottle_dropdown_selection(self):
  fragrance=m.Fragrance.objects.create(organization=self.org,name='Amber',code='FR-AMBER',perfumeOilId=self.ingredients[0])
  bottle=m.Material.objects.create(organization=self.org,name='50 ml Bottle',code='BOT',category='Bottle',unit='pcs')
  size=m.BottleSize.objects.create(organization=self.org,name='50 ml',volumeMl=50,bottleMaterialRef=self.packaging[0],capMaterialRef=self.packaging[1],pumpMaterialRef=self.packaging[2],labelMaterialRef=self.packaging[3])
  payload={**self.body,'fragranceId':fragrance.pk,'bottleSizeId':size.pk};payload.pop('fillVolumeMl')
  response=self.api.post('/api/v1/perfume-products/',payload,format='json');self.assertEqual(response.status_code,201,response.data);product=response.data
  self.assertEqual(product['fragranceId'],fragrance.pk);self.assertEqual(product['fragranceName'],'Amber');self.assertEqual(product['fillVolumeMl'],50)
  data=self.api.get('/api/v1/perfume-workspace/').data
  self.assertEqual(data['fragrances'][0]['id'],fragrance.pk);self.assertIn(size.pk,[b['id'] for b in data['bottleSizes']])
  sale=self.checkout(product);self.assertEqual(sale.status_code,201,sale.data);self.assertEqual(self.balance(self.ingredients[0]),980)
 def test_foreign_fragrance_cannot_be_attached(self):
  org=Organization.objects.create(name='Other perfume shop')
  oil=m.Material.objects.create(organization=org,name='Oil',code='OIL',category='Perfume Oil',unit='ml')
  fragrance=m.Fragrance.objects.create(organization=org,name='Private',code='PRIVATE',perfumeOilId=oil)
  result=self.api.post('/api/v1/perfume-products/',{**self.body,'fragranceId':fragrance.pk},format='json')
  self.assertEqual(result.status_code,400,result.data)

 def test_packaging_deducted_once_with_ingredient_sale(self):
  for material in self.packaging:material.currentCost=3;material.save()
  p=self.product();self.assertEqual([self.balance(x) for x in self.packaging],[100]*4)
  r=self.checkout(p);self.assertEqual(r.status_code,201,r.data)
  self.assertEqual([self.balance(x) for x in self.packaging],[98]*4);self.assertEqual([self.balance(x,self.other) for x in self.packaging],[100]*4)
  line=m.InvoiceLine.objects.get();self.assertEqual(len(line.packagingSnapshot),4);self.assertEqual(line.costSnapshot,112)
  self.checkout(p);self.assertEqual([self.balance(x) for x in self.packaging],[98]*4)
 def test_short_cap_rolls_back_liquid_and_all_packaging(self):
  p=self.product();m.Stock.objects.filter(location=self.br,material=self.packaging[1]).update(quantity=1)
  r=self.checkout(p);self.assertEqual(r.status_code,400,r.data);self.assertIn('pcs',str(r.data));self.assertIn('Cap',str(r.data))
  self.assertEqual(self.balance(self.ingredients[0]),1000);self.assertEqual(self.balance(self.packaging[0]),100);self.assertEqual(m.Invoice.objects.count(),0)
 def test_separate_dip_tube_optional_and_consumed_when_linked(self):
  tube=m.Material.objects.create(organization=self.org,name='Dip tube',code='TUBE',category='Packaging',unit='pcs',packagingType='Dip Tube')
  m.Stock.objects.create(organization=self.org,location=self.br,material=tube,quantity=10)
  self.bottle.dipTubeMaterialRef=tube;self.bottle.save()
  p=self.product();self.assertEqual(self.checkout(p).status_code,201);self.assertEqual(self.balance(tube),8)
  self.assertEqual(len(m.InvoiceLine.objects.get().packagingSnapshot),5)
 def test_bottle_setup_changes_do_not_rewrite_saved_product_packaging(self):
  p=self.product();replacement=m.Material.objects.create(organization=self.org,name='New cap',code='NEWCAP',category='Packaging',unit='pcs',packagingType='Cap')
  self.bottle.capMaterialRef=replacement;self.bottle.save()
  self.assertEqual(self.checkout(p).status_code,201);self.assertEqual(self.balance(self.packaging[1]),98)
 def test_packaging_aggregate_shortage_across_cart(self):
  p=self.product();q=self.product(name='Second perfume');m.Stock.objects.filter(location=self.br,material=self.packaging[0]).update(quantity=3)
  r=self.checkout(p,cart=[dict(productId=x['id'],recipeRevision=1,pricingToken=x.get('pricingToken'),qty=2) for x in [p,q]])
  self.assertEqual(r.status_code,400,r.data);self.assertIn('Bottle',str(r.data));self.assertEqual(m.Invoice.objects.count(),0)
 def test_missing_cap_or_foreign_bottle_rejected(self):
  self.bottle.capMaterialRef=None;self.bottle.save()
  r=self.api.post('/api/v1/perfume-products/',self.body,format='json');self.assertEqual(r.status_code,400,r.data)
  self.assertIn('Cap',str(r.data))

 def test_old_direct_product_must_select_packaging_before_new_sale(self):
  p=self.product();m.Product.objects.filter(pk=p['id']).update(bottleSizeRef=None,packagingRecipe=[])
  r=self.checkout(p);self.assertEqual(r.status_code,400,r.data);self.assertIn('configured bottle',str(r.data))
  self.assertEqual(self.balance(self.ingredients[0]),1000)
 def test_base_category_setup_preserves_existing_categories(self):
  from apps.erp.category_utils import ensure_base_categories
  ensure_base_categories(self.org);ensure_base_categories(self.org)
  self.assertEqual(m.MaterialCategory.objects.filter(organization=self.org).count(),4)
  self.assertEqual(m.MaterialCategory.objects.get(organization=self.org,name='Others').categoryType,'Other')

 def test_raw_packaging_form_price_and_opening_stock(self):
  from apps.erp.category_utils import ensure_base_categories
  ensure_base_categories(self.org);category=m.MaterialCategory.objects.get(organization=self.org,name='Packaging')
  body=dict(name='Gold sticker',categoryRef=category.pk,packagingType='Label',currentCost='2.5',openingStocks=[dict(locationId=self.br.pk,quantity=12)])
  r=self.api.post('/api/v1/inventory/raw-materials/',body,format='json');self.assertEqual(r.status_code,201,r.data)
  material=m.Material.objects.get(pk=r.data['id']);self.assertEqual(material.packagingType,'Label');self.assertEqual(material.currentCost,Decimal('2.5'));self.assertEqual(self.balance(material),12)
 def test_main_category_and_subtype_validation(self):
  from apps.erp.category_utils import ensure_base_categories
  ensure_base_categories(self.org);cat=m.MaterialCategory.objects.get(organization=self.org,name='Packaging')
  r=self.api.post('/api/v1/inventory/raw-materials/',dict(name='Missing subtype',categoryRef=cat.pk,currentCost=1),format='json');self.assertEqual(r.status_code,400,r.data)
  oil=m.MaterialCategory.objects.get(organization=self.org,name='Oil')
  r=self.api.post('/api/v1/inventory/raw-materials/',dict(name='Oil cap',categoryRef=oil.pk,packagingType='Cap'),format='json');self.assertEqual(r.status_code,400,r.data)
 def test_bottle_fields_reject_wrong_packaging_subtypes(self):
  body=dict(name='Wrong package',volumeMl=100,bottleMaterialRef=self.packaging[0].pk,capMaterialRef=self.packaging[1].pk,pumpMaterialRef=self.packaging[3].pk,labelMaterialRef=self.packaging[2].pk)
  r=self.api.post('/api/v1/bottle-sizes/',body,format='json');self.assertEqual(r.status_code,400,r.data);self.assertIn('pumpMaterialRef',r.data)
 def test_label_shortage_blocks_all_deductions(self):
  p=self.product();m.Stock.objects.filter(location=self.br,material=self.packaging[3]).update(quantity=1)
  r=self.checkout(p);self.assertEqual(r.status_code,400,r.data);self.assertIn('Label',str(r.data));self.assertEqual(self.balance(self.ingredients[0]),1000);self.assertEqual(m.Invoice.objects.count(),0)
 def test_packaging_subtype_cannot_change_when_saved_in_product(self):
  self.product()
  from apps.erp.category_utils import ensure_base_categories
  ensure_base_categories(self.org);category=m.MaterialCategory.objects.get(organization=self.org,name='Packaging')
  material=self.packaging[0];material.categoryRef=category;material.category=category.name;material.save()
  r=self.api.patch('/api/v1/inventory/raw-materials/'+material.pk+'/',dict(packagingType='Label'),format='json');self.assertEqual(r.status_code,400,r.data)

 def test_migration_classifies_saved_product_packaging_after_default_changed(self):
  self.product();old_cap=self.packaging[1];old_cap.packagingType='';old_cap.save()
  replacement=m.Material.objects.create(organization=self.org,name='Replacement cap',code='REPLACECAP',category='Packaging',unit='pcs',packagingType='Cap')
  self.bottle.capMaterialRef=replacement;self.bottle.save()
  from importlib import import_module
  from types import SimpleNamespace
  from django.apps import apps
  from django.db import connection
  import_module('apps.erp.migrations.0020_classify_existing_packaging').classify(apps,SimpleNamespace(connection=connection))
  old_cap.refresh_from_db();self.assertEqual(old_cap.packagingType,'Cap')
