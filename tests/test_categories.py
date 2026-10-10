from django.test import TestCase
from rest_framework.test import APIClient
from apps.accounts.models import Organization,User
from apps.erp import models as m
from apps.erp.category_utils import material_type
class CategoryTests(TestCase):
 def setUp(self):
  self.org=Organization.objects.create(name='Categories');self.user=User.objects.create_user(username='categories',organization=self.org,role='owner');self.api=APIClient();self.api.force_authenticate(self.user)
 def category(self,**kw):return self.api.post('/api/v1/inventory/categories/',{'name':'Custom Packaging','categoryType':'Packaging','unit':'pcs','description':'Cartons and caps',**kw},format='json')
 def test_crud_and_protected_usage(self):
  r=self.category();self.assertEqual(r.status_code,201,r.data);pk=r.data['id'];self.assertEqual(self.api.get(f'/api/v1/inventory/categories/{pk}/').status_code,200)
  r=self.api.post('/api/v1/inventory/raw-materials/',{'code':'CUSTOM','name':'Custom Cap','categoryRef':pk,'currentCost':5,'minStock':10},format='json');self.assertEqual(r.status_code,201,r.data);self.assertEqual(r.data['unit'],'pcs');self.assertEqual(r.data['categoryType'],'Packaging')
  self.assertEqual(self.api.patch(f'/api/v1/inventory/categories/{pk}/',{'name':'Renamed Packaging'},format='json').status_code,200);self.assertEqual(m.Material.objects.get(pk=r.data['id']).category,'Renamed Packaging')
  self.assertEqual(self.api.patch(f'/api/v1/inventory/categories/{pk}/',{'unit':'g'},format='json').status_code,400);self.assertEqual(self.api.delete(f'/api/v1/inventory/categories/{pk}/').status_code,409)
  unused=self.category(name='Unused');self.assertEqual(self.api.delete(f"/api/v1/inventory/categories/{unused.data['id']}/").status_code,204)
 def test_liquid_type_unit_validation(self):
  self.assertEqual(self.category(categoryType='Perfume Oil',unit='pcs').status_code,400)
  cat=self.category(name='Essential Oils',categoryType='Perfume Oil',unit='ml').data
  r=self.api.post('/api/v1/inventory/raw-materials/',{'code':'OIL','name':'Oil','categoryRef':cat['id']},format='json');self.assertEqual(r.status_code,201,r.data);self.assertEqual(material_type(m.Material.objects.get(pk=r.data['id'])),'Perfume Oil')
  fragrance=self.api.post('/api/v1/fragrances/',{'name':'Custom scent','code':'CUST','perfumeOilId':r.data['id']},format='json');self.assertEqual(fragrance.status_code,201,fragrance.data)
  self.assertEqual(self.api.post('/api/v1/inventory/raw-materials/',{'code':'BAD','name':'Bad unit','categoryRef':cat['id'],'unit':'g'},format='json').status_code,400)
 def test_scope_and_permissions(self):
  cat=self.category().data;other=Organization.objects.create(name='Other');user=User.objects.create_user(username='othercat',organization=other,role='owner');self.api.force_authenticate(user)
  self.assertEqual(self.api.get(f"/api/v1/inventory/categories/{cat['id']}/").status_code,404)
  self.assertEqual(self.api.post('/api/v1/inventory/raw-materials/',{'code':'FOREIGN','name':'Foreign','categoryRef':cat['id']},format='json').status_code,400)
  user.role='staff';user.save();self.assertEqual(self.category().status_code,403)
 def test_category_delete_duplicate_and_inactive(self):
  cat=self.category().data;self.assertIn(self.category().status_code,[400,409]);self.api.patch(f"/api/v1/inventory/categories/{cat['id']}/",{'status':'inactive'},format='json')
  self.assertEqual(self.api.post('/api/v1/inventory/raw-materials/',{'code':'OFF','name':'Off','categoryRef':cat['id']},format='json').status_code,400)
