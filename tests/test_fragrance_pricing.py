from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APIClient
from apps.erp import models as m
from tests import test_direct_perfume as fixtures

class FragrancePricingTests(TestCase):
 def setUp(self):
  fixtures.DirectPerfumeTests.setUp(self)
  for material in self.ingredients:
   material.currentCost=Decimal('.01');material.save()
 product=fixtures.DirectPerfumeTests.product
 checkout=fixtures.DirectPerfumeTests.checkout
 balance=fixtures.DirectPerfumeTests.balance
 def draft(self,**extra):
  rose=m.Fragrance.objects.create(organization=self.org,name='Rose',code='ROSE',perfumeOilId=self.ingredients[0],pricesByType={'EDP':'80','PARFUM':'100','EDT':'60','EDC':'40','EAU_FRAICHE':'20'})
  oud=m.Fragrance.objects.create(organization=self.org,name='Oud',code='OUD',perfumeOilId=self.ingredients[1],pricesByType={'EDP':'120','PARFUM':'150','EDT':'90','EDC':'50','EAU_FRAICHE':'30'})
  self.rose=rose;self.oud=oud
  return {**self.body,'fragranceType':'EDP','pricingMode':'auto','sellingPrice':'1','recipe':[dict(materialId=self.ingredients[0].pk,fragranceId=rose.pk,percentage=8),dict(materialId=self.ingredients[1].pk,fragranceId=oud.pk,percentage=12),dict(materialId=self.ingredients[2].pk,percentage=80)],**extra}
 def save(self,body):
  r=self.api.post('/api/v1/perfume-products/',body,format='json');self.assertEqual(r.status_code,201,r.data);return r.data
 def test_highest_fragrance_not_sum_and_exact_pos_deduction(self):
  p=self.save(self.draft());self.assertEqual(p['sellingPrice'],120);self.assertEqual(p['pricing']['highestFragrance'],'Oud');self.assertEqual(p['pricing']['basePrice'],'120')
  sale=self.checkout(p);self.assertEqual(sale.status_code,201,sale.data);self.assertEqual(sale.data['invoice']['total'],240)
  self.assertEqual([self.balance(x) for x in self.ingredients],[984,976,840]);self.assertEqual([self.balance(x) for x in self.packaging],[98]*4)
  self.assertEqual(m.InvoiceLine.objects.get().pricingSnapshot['highestFragrance'],'Oud')
 def test_automatic_scales_30_50_75_100_ml(self):
  body=self.draft()
  for volume,expected in [(30,36),(50,60),(75,90),(100,120)]:
   self.bottle.volumeMl=volume;self.bottle.save()
   r=self.api.post('/api/v1/perfume-pricing/',body,format='json');self.assertEqual(r.status_code,200,r.data);self.assertEqual(r.data['sellingPrice'],expected)
 def test_configured_multiplier_and_surcharge(self):
  body=self.draft();self.bottle.priceMultiplier=Decimal('1.25');self.bottle.priceSurcharge=5;self.bottle.save()
  p=self.save(body);self.assertEqual(p['sellingPrice'],155)
 def test_all_types_use_their_own_configured_price_and_oil_range(self):
  body=self.draft()
  for kind,total,expected in [('PARFUM',25,150),('EDP',20,120),('EDT',10,90),('EDC',4,50),('EAU_FRAICHE',2,30)]:
   rows=[{**body['recipe'][0],'percentage':total/2},{**body['recipe'][1],'percentage':total/2},{**body['recipe'][2],'percentage':100-total}]
   r=self.api.post('/api/v1/perfume-pricing/',{**body,'fragranceType':kind,'recipe':rows},format='json');self.assertEqual(r.status_code,200,r.data);self.assertEqual(r.data['sellingPrice'],expected)
 def test_invalid_oil_concentration_and_total_rejected(self):
  body=self.draft();body['fragranceType']='EDT'
  r=self.api.post('/api/v1/perfume-products/',body,format='json');self.assertEqual(r.status_code,400,r.data);self.assertIn('between 5% and 15%',str(r.data))
  body['recipe'][2]['percentage']=79
  self.assertEqual(self.api.post('/api/v1/perfume-pricing/',body,format='json').status_code,400)
 def test_missing_price_never_uses_a_hardcoded_fallback(self):
  body=self.draft();self.oud.pricesByType={};self.oud.save();self.ingredients[1].fragrancePrices={};self.ingredients[1].save()
  r=self.api.post('/api/v1/perfume-products/',body,format='json');self.assertEqual(r.status_code,400,r.data);self.assertIn('configure',str(r.data))
 def test_raw_oil_prices_are_supported(self):
  body=self.draft();body['recipe']=[{k:v for k,v in row.items() if k!='fragranceId'} for row in body['recipe']]
  p=self.save(body);self.assertEqual(p['sellingPrice'],500);self.assertEqual(p['pricing']['selectedFragrances'][0]['source'],'Raw oil')
 def test_explicit_override_and_tampered_auto_price(self):
  body=self.draft();p=self.save(body);self.assertEqual(p['sellingPrice'],120)
  q=self.save({**body,'name':'Overridden','pricingMode':'override','sellingPrice':135});self.assertEqual(q['sellingPrice'],135);self.assertEqual(Decimal(q['pricing']['calculatedPrice']),120)
 def test_fragrance_price_change_blocks_stale_cart_and_preserves_invoice(self):
  body=self.draft();p=self.save(body);self.assertEqual(self.checkout(p).status_code,201);snapshot=m.InvoiceLine.objects.get().pricingSnapshot
  self.oud.pricesByType={'EDP':'140'};self.oud.save()
  stale=self.checkout(p,checkoutKey='new-price-key');self.assertEqual(stale.status_code,400,stale.data);self.assertIn('pricing changed',str(stale.data))
  current=self.api.get('/api/v1/perfume-products/'+p['id']+'/').data;self.assertEqual(current['sellingPrice'],140)
  fresh=self.checkout(current,checkoutKey='fresh-price-key');self.assertEqual(fresh.status_code,201,fresh.data);self.assertEqual(m.InvoiceLine.objects.order_by('created_at').first().pricingSnapshot,snapshot)
 def test_price_configuration_rejects_unknown_negative_and_zero_values(self):
  self.draft()
  for values in [{'WRONG':100},{'EDP':-5},{'EDP':0}]:
   r=self.api.patch('/api/v1/fragrances/'+self.oud.pk+'/',dict(pricesByType=values),format='json');self.assertEqual(r.status_code,400,r.data)
  r=self.api.patch('/api/v1/fragrances/'+self.oud.pk+'/',dict(pricesByType={'EDP':120,'EDT':''}),format='json');self.assertEqual(r.status_code,200,r.data);self.assertEqual(r.data['pricesByType'],{'EDP':'120'})
 def test_fragrance_oil_mismatch_is_rejected(self):
  body=self.draft();body['recipe'][0]['fragranceId']=self.oud.pk
  r=self.api.post('/api/v1/perfume-products/',body,format='json');self.assertEqual(r.status_code,400,r.data)
 def test_branch_three_creation_requires_target(self):
  body=self.draft();virtual=m.Location.objects.create(organization=self.org,name='Virtual 3',code='BR03',kind='Branch',isVirtual=True);virtual.physicalBranches.set([self.br,self.other])
  r=self.api.post('/api/v1/perfume-products/',{**body,'branchId':virtual.pk},format='json');self.assertEqual(r.status_code,400,r.data)
  r=self.api.post('/api/v1/perfume-products/',{**body,'branchId':virtual.pk,'physicalBranchId':self.br.pk},format='json');self.assertEqual(r.status_code,201,r.data)
 def test_pricing_quote_is_read_only_and_preview_token_validated_on_save(self):
  body=self.draft();quote=self.api.post('/api/v1/perfume-pricing/',body,format='json');self.assertEqual(quote.status_code,200,quote.data);self.assertEqual(m.Product.objects.count(),0)
  self.bottle.priceSurcharge=10;self.bottle.save()
  r=self.api.post('/api/v1/perfume-products/',{**body,'pricingToken':quote.data['pricingToken']},format='json');self.assertEqual(r.status_code,400,r.data)

 def test_virtual_account_cannot_omit_branch_selection_on_create(self):
  body=self.draft();virtual=m.Location.objects.create(organization=self.org,name='Virtual account branch',code='VIRTUAL',kind='Branch',isVirtual=True);virtual.physicalBranches.set([self.br,self.other])
  self.user.branch=virtual;self.user.save()
  r=self.api.post('/api/v1/perfume-products/',body,format='json');self.assertEqual(r.status_code,400,r.data)
  r=self.api.post('/api/v1/perfume-products/',{**body,'physicalBranchId':self.br.pk},format='json');self.assertEqual(r.status_code,201,r.data)
 def test_selected_fragrance_cannot_be_deleted(self):
  self.save(self.draft())
  r=self.api.delete('/api/v1/fragrances/'+self.oud.pk+'/');self.assertEqual(r.status_code,400,r.data)
 def test_three_fragrance_combination_uses_highest_not_sum(self):
  body=self.draft();musk=m.Material.objects.create(organization=self.org,name='Musk oil',code='MUSK',category='Perfume Oil',unit='ml',fragrancePrices={'EDP':'95'})
  profile=m.Fragrance.objects.create(organization=self.org,name='Musk',code='MUSKPROFILE',perfumeOilId=musk,pricesByType={'EDP':'95'})
  body['recipe'][1]['percentage']=9;body['recipe'].insert(2,dict(materialId=musk.pk,fragranceId=profile.pk,percentage=3))
  p=self.save(body);self.assertEqual(p['sellingPrice'],120);self.assertEqual(len(p['pricing']['selectedFragrances']),3)

 def test_minimum_is_cost_based_and_ignores_client_value(self):
  body=self.draft();body['minSellingPrice']='9999'
  p=self.save(body)
  self.assertEqual(p['minSellingPrice'],1)
