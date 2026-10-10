from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APIClient
from apps.accounts.models import Organization, User
from apps.erp import models as m


class OpeningStockTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name='Opening stocks')
        self.user = User.objects.create_user(username='opening', organization=self.org, role='owner')
        self.api = APIClient()
        self.api.force_authenticate(self.user)
        self.wh = m.Location.objects.create(organization=self.org, name='Warehouse', code='WH', kind='Warehouse')
        self.br = m.Location.objects.create(organization=self.org, name='Branch', code='BR', kind='Branch')
        self.cat = m.MaterialCategory.objects.create(organization=self.org, name='Oils', categoryType='Perfume Oil', unit='ml')

    def material(self, rows):
        return self.api.post('/api/v1/inventory/raw-materials/', {
            'code':'OPEN', 'name':'Opening oil', 'categoryRef':self.cat.pk,
            'currentCost':'2.50', 'openingStocks':rows,
        }, format='json')

    def test_opening_balances_and_audit_then_purchase(self):
        response = self.material([
            {'locationId':self.wh.pk, 'quantity':'123.4567'},
            {'locationId':self.br.pk, 'quantity':'12.5'},
        ])
        self.assertEqual(response.status_code, 201, response.data)
        material = m.Material.objects.get(pk=response.data['id'])
        self.assertEqual(m.Stock.objects.get(material=material, location=self.wh).quantity, Decimal('123.4567'))
        self.assertEqual(m.Stock.objects.get(material=material, location=self.br).quantity, Decimal('12.5'))
        self.assertEqual(m.Movement.objects.filter(stock__material=material, transaction='OPENING_STOCK').count(), 2)
        self.assertEqual(Decimal(str(response.data['availableStock'])), Decimal('135.9567'))
        self.assertEqual(self.api.patch(f'/api/v1/inventory/raw-materials/{material.pk}/', {'openingStocks':[]}, format='json').status_code, 400)
        supplier = m.Supplier.objects.create(organization=self.org, name='Supplier', code='SUP')
        response = self.api.post('/api/v1/purchases/orders/', {'supplierName':supplier.name, 'warehouseName':self.wh.name, 'items':[{'material':material.code, 'qty':2, 'rate':3}]}, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(m.PurchaseLine.objects.get(order_id=response.data['id']).qty, Decimal('2'))

    def test_invalid_opening_requests_leave_no_material(self):
        other = Organization.objects.create(name='Other')
        foreign = m.Location.objects.create(organization=other, name='Foreign', code='F', kind='Warehouse')
        for rows in [
            [{'locationId':foreign.pk, 'quantity':1}],
            [{'locationId':self.wh.pk, 'quantity':-1}],
            [{'locationId':self.wh.pk, 'quantity':1}, {'locationId':self.wh.pk, 'quantity':2}],
        ]:
            self.assertEqual(self.material(rows).status_code, 400)
            self.assertFalse(m.Material.objects.filter(code='OPEN').exists())
            self.assertEqual(m.Movement.objects.count(), 0)
        self.user.role='warehouse_manager'
        self.user.warehouse=self.wh
        self.user.save()
        self.assertEqual(self.material([{'locationId':self.br.pk,'quantity':1}]).status_code,403)
        self.assertFalse(m.Material.objects.filter(code='OPEN').exists())

    def test_branch_requires_owned_active_warehouse_and_can_edit(self):
        endpoint='/api/v1/branches/'
        data={'code':'NEW', 'name':'New branch'}
        self.assertEqual(self.api.post(endpoint,data,format='json').status_code,400)
        self.assertEqual(self.api.post(endpoint,{**data,'warehouse':self.br.pk},format='json').status_code,400)
        other=Organization.objects.create(name='Other')
        foreign=m.Location.objects.create(organization=other,name='Foreign',code='F',kind='Warehouse')
        self.assertEqual(self.api.post(endpoint,{**data,'warehouse':foreign.pk},format='json').status_code,400)
        response=self.api.post(endpoint,{**data,'warehouse':self.wh.pk},format='json')
        self.assertEqual(response.status_code,201,response.data)
        self.assertEqual(response.data['warehouseName'],self.wh.name)
        self.assertEqual(self.api.patch(endpoint+response.data['id']+'/',{'warehouse':None},format='json').status_code,400)
        self.assertEqual(self.api.patch(endpoint+self.br.pk+'/',{'warehouse':self.wh.pk},format='json').status_code,200)

    def test_piece_quantities_and_inactive_locations(self):
        self.cat.categoryType='Packaging'
        self.cat.unit='pcs'
        self.cat.save()
        self.assertEqual(self.material([{'locationId':self.wh.pk,'quantity':'1.5'}]).status_code,400)
        self.wh.status='inactive'
        self.wh.save()
        self.assertEqual(self.material([{'locationId':self.wh.pk,'quantity':1}]).status_code,400)
        self.assertEqual(self.api.post('/api/v1/branches/',{'name':'Inactive warehouse branch','code':'OFF','warehouse':self.wh.pk},format='json').status_code,400)
        self.assertFalse(m.Material.objects.filter(code='OPEN').exists())
