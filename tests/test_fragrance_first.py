from copy import deepcopy
from decimal import Decimal
from django.test import TestCase
from django.db.models.deletion import ProtectedError
from apps.accounts.models import Organization,Role,UserRoleAssignment
from apps.erp import models as m
from tests import test_direct_perfume as fixtures

class FragranceFirstTests(TestCase):
 def setUp(self):
  fixtures.DirectPerfumeTests.setUp(self)
  for material in self.ingredients:material.currentCost=Decimal('.01');material.save()
  self.profiles=[]
  for i,(oil,name,price) in enumerate(zip(self.ingredients[:2],['Rose','Oud'],['800','1200'])):
   self.profiles.append(m.Fragrance.objects.create(organization=self.org,name=name,code=f'F{i}',perfumeOilId=oil,defaultType='EDP',defaultOilPercentage=20,solventRecipe=[dict(materialId=self.ingredients[2].pk,share='100')],defaultBottleSize=self.bottle,pricesByType={'EDP':price,'PARFUM':price}))
 def data(self,**extra):return {**dict(name='Royal Rose Oud',branchId=self.br.pk,fragranceSelections=[dict(fragranceId=self.profiles[0].pk,percentage='8'),dict(fragranceId=self.profiles[1].pk,percentage='12')],pricingMode='auto'),**extra}
 def preview(self,body=None):return self.api.post('/api/v1/perfume-pricing/',body or self.data(),format='json')
 def save(self,body=None):
  r=self.api.post('/api/v1/perfume-products/',body or self.data(),format='json');self.assertEqual(r.status_code,201,r.data);return r.data
 def test_defaults_highest_and_no_stock_consumption(self):
  before=list(m.Stock.objects.values_list('pk','quantity'));p=self.save()
  self.assertTrue(p['fragranceFirst']);self.assertEqual(p['fragranceType'],'EDP');self.assertEqual(p['sellingPrice'],1200)
  self.assertEqual([Decimal(r['percentage']) for r in p['recipe']],[8,12,80]);self.assertEqual(p['bottleSizeId'],self.bottle.pk)
  self.assertEqual(list(m.Stock.objects.values_list('pk','quantity')),before)
 def test_single_profile_uses_entire_20_percent(self):
  p=self.save(self.data(fragranceSelections=[dict(fragranceId=self.profiles[0].pk,percentage=3)]));self.assertEqual([Decimal(r['percentage']) for r in p['recipe']],[20,80])
 def test_ml_changes_with_bottle_size(self):
  for volume,expected,price in [(50,[4,6,40],600),(100,[8,12,80],1200),(30,[Decimal('2.4'),Decimal('3.6'),24],360)]:
   self.bottle.volumeMl=volume;self.bottle.save();r=self.preview();self.assertEqual(r.status_code,200,r.data)
   self.assertEqual([Decimal(row['requiredMl']) for row in r.data['plan']['recipe']],expected);self.assertEqual(r.data['sellingPrice'],price)
 def test_fourth_duplicate_zero_wrong_total_and_precision(self):
  rows=self.data()['fragranceSelections']
  for choice in [rows*2,[rows[0]]*2,[dict(rows[0],percentage=0),dict(rows[1],percentage=20)],[dict(rows[0],percentage=20),dict(rows[1],percentage=20)],[dict(rows[0],percentage='8.00001'),rows[1]]]:
   r=self.preview(self.data(fragranceSelections=choice));self.assertEqual(r.status_code,400,r.data)
 def test_three_fragrances_use_max(self):
  oil=m.Material.objects.create(organization=self.org,name='Musk Oil',code='M',category='Perfume Oil',unit='ml',currentCost='.01')
  f=m.Fragrance.objects.create(organization=self.org,name='Musk',code='M',perfumeOilId=oil,defaultType='EDP',defaultOilPercentage=20,solventRecipe=self.profiles[0].solventRecipe,pricesByType={'EDP':'950'})
  rows=[dict(fragranceId=p.pk,percentage=v) for p,v in zip(self.profiles+[f],[8,8,4])]
  self.assertEqual(self.save(self.data(fragranceSelections=rows,bottleSizeId=self.bottle.pk))['sellingPrice'],1200)
 def test_missing_incompatible_and_invalid_edp_defaults(self):
  self.profiles[0].defaultType='';self.profiles[0].save();self.assertEqual(self.preview().status_code,400)
  self.profiles[0].defaultType='PARFUM';self.profiles[0].defaultOilPercentage=25;self.profiles[0].save();self.assertEqual(self.preview().status_code,400)
  r=self.api.patch(f'/api/v1/fragrances/{self.profiles[1].pk}/',{'defaultOilPercentage':18},format='json');self.assertEqual(r.status_code,400,r.data)
 def test_multiple_solvents_rounding_and_invalid_share(self):
  solvent=m.Material.objects.create(organization=self.org,name='DPG',code='DPG',category='Solvent',unit='ml')
  defaults=[dict(materialId=self.ingredients[2].pk,share='66.6667'),dict(materialId=solvent.pk,share='33.3333')]
  for f in self.profiles:f.solventRecipe=defaults;f.save()
  self.bottle.volumeMl=Decimal('33.333');self.bottle.save();r=self.preview();self.assertEqual(r.status_code,200,r.data)
  self.assertEqual(sum(Decimal(x['percentage']) for x in r.data['plan']['recipe']),100);self.assertEqual(sum(Decimal(x['requiredMl']) for x in r.data['plan']['recipe']),Decimal('33.333'))
  defaults[0]['share']='50';self.profiles[0].solventRecipe=defaults;self.profiles[0].save();self.assertEqual(self.preview().status_code,400)
 def test_conflicting_default_bottles(self):
  self.profiles[1].defaultBottleSize=None;self.profiles[1].save();self.assertEqual(self.preview().status_code,400)
  self.assertEqual(self.preview(self.data(bottleSizeId=self.bottle.pk)).status_code,200)
 def test_exact_pos_stock_and_retry(self):
  self.bottle.volumeMl=50;self.bottle.save();p=self.save();r=fixtures.DirectPerfumeTests.checkout(self,p);self.assertEqual(r.status_code,201,r.data)
  self.assertEqual([fixtures.DirectPerfumeTests.balance(self,x) for x in self.ingredients],[992,988,920]);self.assertEqual([fixtures.DirectPerfumeTests.balance(self,x) for x in self.packaging],[98]*4)
  self.assertIn(fixtures.DirectPerfumeTests.checkout(self,p).status_code,[200,201]);self.assertEqual(m.Invoice.objects.count(),1)
  self.assertEqual(m.Stock.objects.get(material=self.ingredients[0],location=self.other).quantity,1000)
 def test_shortage_rolls_back_whole_sale(self):
  p=self.save();m.Stock.objects.filter(material=self.packaging[3],location=self.br).update(quantity=1)
  r=fixtures.DirectPerfumeTests.checkout(self,p);self.assertEqual(r.status_code,400,r.data);self.assertFalse(m.Invoice.objects.exists())
  self.assertEqual(m.Stock.objects.get(material=self.ingredients[0],location=self.br).quantity,1000)
 def test_stale_price_and_product_revision(self):
  quote=self.preview().data;self.profiles[1].pricesByType={'EDP':'1300'};self.profiles[1].save()
  r=self.api.post('/api/v1/perfume-products/',{**self.data(),'pricingToken':quote['pricingToken']},format='json');self.assertEqual(r.status_code,400)
  p=self.save();r=self.api.patch(f"/api/v1/perfume-products/{p['id']}/",{**self.data(),'name':'New name','recipeRevision':p['recipeRevision']},format='json');self.assertEqual(r.status_code,200,r.data)
  self.assertEqual(r.data['recipeRevision'],2);r=self.api.patch(f"/api/v1/perfume-products/{p['id']}/",{**self.data(),'recipeRevision':1},format='json');self.assertEqual(r.status_code,400)
 def test_saved_defaults_and_invoice_snapshots_stay_fixed(self):
  p=self.save();r=fixtures.DirectPerfumeTests.checkout(self,p);self.assertEqual(r.status_code,201,r.data)
  line=m.InvoiceLine.objects.get();old=(deepcopy(line.recipeSnapshot),deepcopy(line.pricingSnapshot))
  self.profiles[0].defaultType='PARFUM';self.profiles[0].defaultOilPercentage=30;self.profiles[0].save()
  current=self.api.get(f"/api/v1/perfume-products/{p['id']}/").data
  self.assertEqual(current['fragranceType'],'EDP');self.assertEqual([{k:v for k,v in r.items() if k!='available'} for r in current['recipe']],[{k:v for k,v in r.items() if k!='available'} for r in p['recipe']]);self.assertEqual(current['pricingToken'],p['pricingToken'])
  line.refresh_from_db();self.assertEqual((line.recipeSnapshot,line.pricingSnapshot),old)
 def test_legacy_editor_preserved(self):
  p=fixtures.DirectPerfumeTests.product(self);r=self.api.patch(f"/api/v1/perfume-products/{p['id']}/",{**self.body,'name':'Edited legacy','recipeRevision':p['recipeRevision']},format='json')
  self.assertEqual(r.status_code,200,r.data);self.assertFalse(r.data['fragranceFirst'])
 def test_surcharge_and_override_keep_existing_policy(self):
  self.bottle.priceMultiplier=Decimal('1.25');self.bottle.priceSurcharge=20;self.bottle.save();self.assertEqual(self.save()['sellingPrice'],1520)
  self.assertEqual(self.save(self.data(name='Override',pricingMode='override',sellingPrice=1400))['sellingPrice'],1400)
 def test_knots_are_informational(self):
  knot=m.Knot.objects.create(organization=self.org,name='Premium Knot',price=999,priceBasis='bottle',description='Details')
  self.profiles[0].knots.add(knot);p=self.save();self.assertEqual(p['sellingPrice'],1200);self.assertFalse(p['blendConfig']['knots'][0]['applied'])
  self.assertEqual(Decimal(p['blendConfig']['knots'][0]['price']),999)
 def test_other_type_and_missing_price(self):
  for f in self.profiles:f.defaultType='PARFUM';f.defaultOilPercentage=25;f.save()
  body=self.data(fragranceSelections=[dict(fragranceId=self.profiles[0].pk,percentage=10),dict(fragranceId=self.profiles[1].pk,percentage=15)])
  self.assertEqual(self.preview(body).status_code,200)
  self.profiles[1].pricesByType={};self.profiles[1].save();self.ingredients[1].fragrancePrices={};self.ingredients[1].save();self.assertEqual(self.preview(body).status_code,400)

 def test_fragrance_api_configuration_and_workspace(self):
  knot=m.Knot.objects.create(organization=self.org,name='API Knot',price=10,priceBasis='ml')
  r=self.api.post('/api/v1/fragrances/',dict(name='Configured via API',perfumeOilId=self.ingredients[0].pk,defaultType='EDP',defaultOilPercentage=None,defaultBottleSize=self.bottle.pk,solventRecipe=[dict(materialId=self.ingredients[2].pk,share=100)],knots=[knot.pk],pricesByType={'EDP':'700'}),format='json')
  self.assertEqual(r.status_code,201,r.data);self.assertEqual(Decimal(r.data['defaultOilPercentage']),20);self.assertEqual(r.data['knots'],[knot.pk]);self.assertEqual(r.data['knotDetails'][0]['description'],knot.description)
  workspace=self.api.get('/api/v1/perfume-workspace/');self.assertEqual(workspace.status_code,200,workspace.data)
  profile=next(x for x in workspace.data['fragrances'] if x['id']==r.data['id']);self.assertEqual(profile['defaultBottleSize'],self.bottle.pk)
  plan=self.api.post('/api/v1/fragrance-plan/',dict(fragranceSelections=[dict(fragranceId=r.data['id'])]),format='json');self.assertEqual(plan.status_code,200,plan.data)
  self.assertEqual([Decimal(row['requiredMl']) for row in plan.data['recipe']],[20,80])
 def test_configuration_rejects_foreign_oil_and_invalid_solvents(self):
  org=Organization.objects.create(name='Other tenant');oil=m.Material.objects.create(organization=org,name='Private oil',code='X',category='Perfume Oil',unit='ml')
  r=self.api.post('/api/v1/fragrances/',dict(name='Bad tenant',perfumeOilId=oil.pk),format='json');self.assertEqual(r.status_code,400)
  r=self.api.patch(f'/api/v1/fragrances/{self.profiles[0].pk}/',dict(solventRecipe=[dict(materialId=self.ingredients[0].pk,share=100)]),format='json');self.assertEqual(r.status_code,400)
  r=self.api.post('/api/v1/perfume-pricing/',self.data(fragranceType='PARFUM',recipe=[dict(materialId=oil.pk,percentage=100)]),format='json')
  self.assertEqual(r.status_code,200,r.data);self.assertEqual(r.data['plan']['fragranceType'],'EDP')

class KnotCrudTests(TestCase):
 def setUp(self):fixtures.DirectPerfumeTests.setUp(self)
 def create(self,**extra):return self.api.post('/api/v1/knots/',{**dict(name='  Premium   Knot ',price='25.5',priceBasis='reference_100ml',description='Details'),**extra},format='json')
 def test_crud_duplicate_and_protected_delete(self):
  r=self.create();self.assertEqual(r.status_code,201,r.data);k=r.data;self.assertEqual(k['name'],'Premium Knot');self.assertEqual(self.create(name='premium knot').status_code,400)
  f=m.Fragrance.objects.create(organization=self.org,name='Rose',code='F',perfumeOilId=self.ingredients[0]);f.knots.add(m.Knot.objects.get(pk=k['id']))
  self.assertEqual(self.api.delete('/api/v1/knots/'+k['id']+'/').status_code,400)
  with self.assertRaises(ProtectedError):m.Knot.objects.get(pk=k['id']).delete()
  self.assertEqual(self.api.patch('/api/v1/knots/'+k['id']+'/',{'price':'30','status':'inactive'},format='json').status_code,200)
  f.knots.clear();self.assertEqual(self.api.delete('/api/v1/knots/'+k['id']+'/').status_code,204)
 def test_invalid_values_and_tenant_scope(self):
  self.assertEqual(self.create(price=-1).status_code,400);self.assertEqual(self.create(priceBasis='unknown').status_code,400)
  org=Organization.objects.create(name='Foreign');k=m.Knot.objects.create(organization=org,name='Private',price=1,priceBasis='ml')
  self.assertEqual(self.api.get(f'/api/v1/knots/{k.pk}/').status_code,404)
  r=self.api.post('/api/v1/fragrances/',dict(name='Bad link',perfumeOilId=self.ingredients[0].pk,knots=[k.pk]),format='json');self.assertEqual(r.status_code,400,r.data)
 def test_read_role_cannot_modify(self):
  from django.contrib.auth import get_user_model
  user=get_user_model().objects.create_user(username='reader',organization=self.org,role='cashier')
  role=Role.objects.create(organization=self.org,name='Knots reader',permissions=['inventory.knot.view'],scope='organization')
  UserRoleAssignment.objects.create(user=user,role=role)
  self.api.force_authenticate(user);self.assertEqual(self.api.get('/api/v1/knots/').status_code,200);self.assertEqual(self.create().status_code,403)
