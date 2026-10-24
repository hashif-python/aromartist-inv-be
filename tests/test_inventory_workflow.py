from django.test import TestCase
from django.core.management import call_command
from rest_framework.test import APIClient
from apps.accounts.models import Organization,User
from apps.erp import models as m
from apps.erp.workflow import costing

class InventoryWorkflowTests(TestCase):
 def setUp(self):
  call_command('seed_perfumosol_demo',verbosity=0)
  self.org=Organization.objects.get(name='Perfumosol Demonstration');self.user=User.objects.create_user(username='workflow_owner',organization=self.org,role='owner')
  self.api=APIClient();self.api.force_authenticate(self.user);self.product=m.Product.objects.filter(organization=self.org).first();self.variant=self.product.variants.order_by('fillVolumeMl').first()
  self.source=m.Location.objects.get(organization=self.org,code='WH01');self.dest=m.Location.objects.get(organization=self.org,code='WH03');self.branch=m.Location.objects.get(organization=self.org,code='BR01')
 def payload(self): return dict(variantId=self.variant.pk,branchId=self.branch.pk,sourceWarehouseId=self.source.pk,finishedWarehouseId=self.dest.pk,quantity=10,requestKey='confirmation-key')
 def post(self,data=None):return self.api.post(f'/api/v1/products/{self.product.pk}/manufacture/',data or self.payload(),format='json')
 def test_volumes_and_no_stock_on_creation(self):
  for v in self.product.variants.all():
   self.assertEqual(sum(r['qty'] for r in costing(v)['rows'] if r['unit']=='ml'),v.fillVolumeMl)
   self.assertEqual(sum(r.percentage for r in v.formulaId.percentages.all()),100)
  self.assertFalse(m.Stock.objects.filter(variant__productId=self.product).exists())
 def test_production_deductions_and_idempotent_retry(self):
  response=self.post();self.assertEqual(response.status_code,200,response.data);b=m.Batch.objects.get(pk=response.data['id'])
  for line in b.consumptions.all():
   initial=10000 if line.material.unit=='ml' else 500
   self.assertEqual(m.Stock.objects.get(location=self.source,material=line.material).quantity,initial-line.actual)
  self.assertEqual(m.Stock.objects.get(location=self.dest,variant=self.variant).quantity,10)
  self.assertFalse(m.Stock.objects.filter(location=self.source,variant=self.variant).exists())
  count=m.Movement.objects.count();retry=self.post();self.assertEqual(retry.data['id'],b.pk);self.assertEqual(m.Movement.objects.count(),count)
  self.assertEqual(self.post({**self.payload(),'quantity':11}).status_code,400)
 def test_insufficient_stock_rolls_back(self):
  count=m.Movement.objects.count();self.assertEqual(self.post({**self.payload(),'quantity':1000000}).status_code,400);self.assertFalse(m.Batch.objects.exists());self.assertEqual(count,m.Movement.objects.count())
 def test_seed_idempotent(self):
  counts=(m.Material.objects.count(),m.Formula.objects.count(),m.Movement.objects.count());call_command('seed_perfumosol_demo',verbosity=0);self.assertEqual(counts,(m.Material.objects.count(),m.Formula.objects.count(),m.Movement.objects.count()))
 def test_invalid_percentage_and_duplicate(self):
  f=self.variant.formulaId;rows=[dict(materialId=x.material_id,percentage=x.percentage) for x in f.percentages.all()]
  for bad in [[{**rows[0],'percentage':-1},*rows[1:]],[{**rows[0],'percentage':17},*rows[1:]],[rows[0],rows[0],*rows[1:]]]:
   r=self.api.post('/api/v1/formulas/',dict(code='BAD',name='Bad',fragranceId=f.fragranceId_id,percentageRecipe=True,percentageIngredients=bad),format='json');self.assertEqual(r.status_code,400)
 def test_cost_changes_preserve_consumption_snapshot(self):
  before=costing(self.variant)['totalEstimatedUnitCost'];self.assertEqual(self.post().status_code,200);b=m.Batch.objects.first();old=list(b.consumptions.values_list('rate',flat=True));mat=self.variant.formulaId.percentages.first().material;mat.currentCost+=10;mat.save();self.assertGreater(costing(self.variant)['totalEstimatedUnitCost'],before);self.assertEqual(old,list(b.consumptions.values_list('rate',flat=True)))
  f=self.variant.formulaId;r=self.api.put(f'/api/v1/formulas/{f.pk}/',dict(code='EDIT',name='Edit',fragranceId=f.fragranceId_id,percentageRecipe=True,percentageIngredients=[]),format='json');self.assertEqual(r.status_code,400)
 def test_tenant_scope(self):
  org=Organization.objects.create(name='Other');user=User.objects.create_user(username='other',organization=org,role='owner');self.api.force_authenticate(user);self.assertEqual(self.api.get(f'/api/v1/products/{self.product.pk}/workspace/').status_code,404)
 def test_duplicate_sku_rolls_back_parent(self):
  f=self.variant.formulaId;count=m.Product.objects.count();r=self.api.post('/api/v1/products/unified/',dict(name='Rollback',code='ROLLBACK',fragranceId=f.fragranceId_id,formulaId=f.pk,variants=[dict(sku=self.variant.sku)]),format='json');self.assertEqual(r.status_code,400);self.assertEqual(count,m.Product.objects.count())
 def test_workspace_includes_costs_and_balances(self):
  self.assertEqual(self.post().status_code,200);r=self.api.get(f'/api/v1/products/{self.product.pk}/workspace/');self.assertEqual(r.status_code,200,r.data);self.assertEqual(len(r.data['stock']),1);self.assertEqual(len(r.data['production']),1)

 def test_unused_product_delete_and_used_protection(self):
  unused=m.Product.objects.exclude(pk=self.product.pk).first();variants=list(unused.variants.values_list('pk',flat=True));self.assertEqual(self.api.delete(f'/api/v1/products/{unused.pk}/').status_code,204);self.assertFalse(m.Variant.objects.filter(pk__in=variants).exists())
  self.assertEqual(self.post().status_code,200);self.assertEqual(self.api.delete(f'/api/v1/products/{self.product.pk}/').status_code,400)
 def test_inline_pricing_preserves_movements(self):
  self.assertEqual(self.post().status_code,200);count=m.Movement.objects.count();r=self.api.post(f'/api/v1/products/variants/{self.variant.pk}/pricing/',{'sellingPrice':999},format='json');self.assertEqual(r.status_code,200,r.data);self.variant.refresh_from_db();self.assertEqual(self.variant.sellingPrice,999);self.assertEqual(m.Movement.objects.count(),count)
