from django.test import TestCase
from django.core.management import call_command
from rest_framework.test import APIClient
from apps.accounts.models import Organization,User
from apps.erp import models as m
from apps.erp.workflow import costing

class AutomaticProductTests(TestCase):
 def setUp(self):
  call_command('seed_perfumosol_demo',verbosity=0)
  self.org=Organization.objects.get(name='Perfumosol Demonstration');self.user=User.objects.create_user(username='automatic',organization=self.org,role='owner')
  self.api=APIClient();self.api.force_authenticate(self.user);self.v=m.Variant.objects.filter(organization=self.org).first();self.size=self.v.bottleSizeId
  self.pump=m.Material.objects.filter(organization=self.org,name__icontains='pump').first();self.cap=m.Material.objects.filter(organization=self.org,name__icontains='cap').first()
  self.size.pumpMaterialRef=self.pump;self.size.capMaterialRef=self.cap;self.size.save()
 def payload(self):
  return dict(name='Auto perfume',code='AUTO',fragranceId=self.v.fragranceId_id,formulaId=self.v.formulaId_id,variants=[dict(sku='AUTOSKU',bottleSizeId=self.size.pk,concentrationId=self.v.concentrationId_id,plannedQuantity=100,automaticPackaging=True,sellingPrice=999999,packaging=[],fillVolumeMl=1)])
 def post(self,data=None):return self.api.post('/api/v1/products/unified/',data or self.payload(),format='json')
 def test_quantities_price_and_no_stock_mutation(self):
  count=m.Movement.objects.count();r=self.post();self.assertEqual(r.status_code,201,r.data)
  v=m.Variant.objects.get(productId_id=r.data['id']);self.assertTrue(v.sku.startswith('SKU-')); self.assertEqual(v.plannedQuantity,100);self.assertEqual(v.fillVolumeMl,self.size.volumeMl)
  self.assertEqual(set(v.packaging.values_list('material_id',flat=True)),{self.size.bottleMaterialRef_id,self.pump.pk,self.cap.pk});self.assertTrue(all(x.qty==1 for x in v.packaging.all()))
  self.assertEqual(v.sellingPrice,costing(v)['totalEstimatedUnitCost']);self.assertEqual(m.Movement.objects.count(),count);self.assertFalse(m.Stock.objects.filter(variant=v).exists())
 def test_invalid_quantity_rejected(self):
  for qty in [0,-1,'2.5',100000001]:
   data=self.payload();data['variants'][0]['plannedQuantity']=qty;self.assertEqual(self.post(data).status_code,400)
 def test_ambiguous_pump_requires_default(self):
  self.size.pumpMaterialRef=None;self.size.save()
  cat=self.pump.categoryRef;m.Material.objects.create(organization=self.org,name='Second pump',code='PUMPALT',categoryRef=cat,category=cat.name,unit='pcs')
  self.assertEqual(self.post().status_code,400);self.assertFalse(m.Product.objects.filter(code='AUTO').exists())
 def test_incompatible_default_rejected(self):
  other=m.BottleSize.objects.filter(organization=self.org).exclude(pk=self.size.pk).first();self.pump.compatibleBottleSizes.set([other]);self.assertEqual(self.post().status_code,400)
 def test_default_relations_are_tenant_scoped(self):
  other=Organization.objects.create(name='Foreign defaults');mat=m.Material.objects.create(organization=other,name='Foreign pump',code='FOREIGN',category='Pump',unit='pcs')
  r=self.api.patch(f'/api/v1/bottle-sizes/{self.size.pk}/',{'pumpMaterialRef':mat.pk},format='json');self.assertEqual(r.status_code,400)
