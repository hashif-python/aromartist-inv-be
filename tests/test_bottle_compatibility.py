from django.test import TestCase
from django.core.management import call_command
from rest_framework.test import APIClient
from apps.accounts.models import Organization, User
from apps.erp import models as m

class BottleCompatibilityTests(TestCase):
 def setUp(self):
  call_command('seed_perfumosol_demo',verbosity=0)
  self.org=Organization.objects.get(name='Perfumosol Demonstration')
  self.user=User.objects.create_user(username='compatibility',organization=self.org,role='owner')
  self.api=APIClient();self.api.force_authenticate(self.user)
  self.v=m.Variant.objects.filter(organization=self.org).first()
  self.size=self.v.bottleSizeId
  self.other=m.BottleSize.objects.filter(organization=self.org).exclude(pk=self.size.pk).first()
  self.cat=m.MaterialCategory.objects.filter(organization=self.org,categoryType='Packaging').first()
  self.cap=m.Material.objects.create(organization=self.org,name='Compatible cap',code='COMPAT',categoryRef=self.cat,category=self.cat.name,unit=self.cat.unit)
 def create_product(self):
  v=self.v
  return self.api.post('/api/v1/products/unified/',dict(name='Compatibility product',code='COMPATPRODUCT',fragranceId=v.fragranceId_id,formulaId=v.formulaId_id,variants=[dict(sku='COMPATSKU',bottleSizeId=self.size.pk,concentrationId=v.concentrationId_id,fillVolumeMl=v.fillVolumeMl,sellingPrice=100,packaging=[dict(materialId=self.size.bottleMaterialRef_id,qty=1),dict(materialId=self.cap.pk,qty=1)])]),format='json')
 def test_matching_multiple_and_unrestricted(self):
  self.cap.compatibleBottleSizes.set([self.size,self.other])
  r=self.create_product();self.assertEqual(r.status_code,201,r.data)
  self.cap.compatibleBottleSizes.clear()
  self.assertEqual(self.api.get(f'/api/v1/inventory/raw-materials/{self.cap.pk}/').data['compatibleBottleSizes'],[])
 def test_incompatible_rejected_and_rollback(self):
  self.cap.compatibleBottleSizes.set([self.other]);count=m.Product.objects.count()
  r=self.create_product();self.assertEqual(r.status_code,400,r.data);self.assertEqual(m.Product.objects.count(),count)
 def test_restriction_cannot_break_existing_variant(self):
  self.assertEqual(self.create_product().status_code,201)
  r=self.api.patch(f'/api/v1/inventory/raw-materials/{self.cap.pk}/',{'compatibleBottleSizes':[self.other.pk]},format='json');self.assertEqual(r.status_code,400,r.data)
  r=self.api.patch(f'/api/v1/inventory/raw-materials/{self.cap.pk}/',{'compatibleBottleSizes':[self.size.pk]},format='json');self.assertEqual(r.status_code,200,r.data)
 def test_raw_material_create_edit_and_tenant_scope(self):
  data=dict(packagingType='Pump',name='Size pump',code='SIZEPUMP',categoryRef=self.cat.pk,compatibleBottleSizes=[self.size.pk,self.other.pk])
  r=self.api.post('/api/v1/inventory/raw-materials/',data,format='json');self.assertEqual(r.status_code,201,r.data);self.assertEqual(set(r.data['compatibleBottleSizes']),{str(self.size.pk),str(self.other.pk)})
  foreign=Organization.objects.create(name='Foreign sizes');b=m.Material.objects.create(organization=foreign,name='Bottle',code='B',category='Bottle',unit='pcs');size=m.BottleSize.objects.create(organization=foreign,name='Foreign',volumeMl=100,bottleMaterialRef=b)
  self.assertEqual(self.api.patch(f"/api/v1/inventory/raw-materials/{r.data['id']}/",{'compatibleBottleSizes':[size.pk]},format='json').status_code,400)
 def test_nonpackaging_rejected(self):
  oil=m.Material.objects.filter(organization=self.org,categoryRef__categoryType='Perfume Oil').first()
  self.assertEqual(self.api.patch(f'/api/v1/inventory/raw-materials/{oil.pk}/',{'compatibleBottleSizes':[self.size.pk]},format='json').status_code,400)
