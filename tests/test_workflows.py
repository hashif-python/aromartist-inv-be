from datetime import date
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core import mail
from rest_framework.test import APIClient
from apps.accounts.models import Organization
from apps.erp import models as m, services as svc

class Workflows(TestCase):
 def setUp(self):
  self.org=Organization.objects.create(name='Aromartist');self.other=Organization.objects.create(name='Other shop')
  def create(model,**kw): return model.objects.create(organization=self.org,**kw)
  self.wh=create(m.Location,name='Warehouse',code='WH',kind='Warehouse');self.br=create(m.Location,name='Branch',code='BR',kind='Branch');self.br2=create(m.Location,name='Other branch',code='BR2',kind='Branch')
  self.user=get_user_model().objects.create_user(username='owner',password='Strong-test-238!',organization=self.org,role='owner',branch=self.br,warehouse=self.wh,email='owner@example.com')
  self.api=APIClient();self.api.force_authenticate(self.user)
  self.sup=create(m.Supplier,name='Supplier',code='SUP')
  self.oil=create(m.Material,name='Oil',code='OIL',category='Perfume Oil',unit='ml',currentCost=8,supplier=self.sup,minStock=20)
  self.sol=create(m.Material,name='Solvent',code='SOL',category='Solvent',unit='ml',currentCost=Decimal('.5'));self.bot=create(m.Material,name='Bottle',code='BOT',category='Bottle',unit='pcs',currentCost=22)
  self.fr=create(m.Fragrance,name='Fragrance',code='FR',perfumeOilId=self.oil);self.conc=create(m.Concentration,name='EDP',code='EDP',oilPercentage=20);self.size=create(m.BottleSize,name='50 ml',volumeMl=50,bottleMaterialRef=self.bot)
  self.basis={'fragranceId':self.fr.pk,'concentrationId':self.conc.pk,'bottleSizeId':self.size.pk,'laborCost':10,'cleaningAllocation':2,'otherCost':3}
  self.form=svc.save_formula(self.user,self.basis);self.prod=create(m.Product,name='Perfume',code='P')
  self.v=create(m.Variant,name='Perfume 50 EDP',productId=self.prod,fragranceId=self.fr,bottleSizeId=self.size,concentrationId=self.conc,formulaId=self.form,sku='P50',costPrice=137,sellingPrice=599,minSellingPrice=500,mrp=699)
  for mat,qty in [(self.oil,1000),(self.sol,4000),(self.bot,100)]: create(m.Stock,location=self.wh,material=mat,quantity=qty)
  create(m.Stock,location=self.br,variant=self.v,quantity=20)
 def post(self,url,data,code=201):
  r=self.api.post('/api/v1/'+url,data,format='json');self.assertEqual(r.status_code,code,getattr(r,'data',None));return r.data
 def get(self,url):
  r=self.api.get('/api/v1/'+url);self.assertEqual(r.status_code,200,getattr(r,'data',None));return r.data
 def balance(self,item,loc): return m.Stock.objects.get(location=loc,**{'material' if isinstance(item,m.Material) else 'variant':item}).quantity
 def sale(self,**kw): return self.post('sales/pos/checkout/',{'cart':[{'id':self.v.pk,'qty':2,'sellingPrice':1,'costPrice':0}],'branchId':self.br.pk,'paymentMethod':'Cash',**kw})['invoice']
 def po(self): return self.post('purchases/orders/',{'supplierName':'Supplier','warehouseName':'Warehouse','orderDate':str(date.today()),'expectedDate':str(date.today()),'items':[{'material':'Oil','qty':20,'rate':10,'discount':2,'tax':1}]})
 def batch(self): return self.post('production/batches/',{'productVariantId':self.v.pk,'warehouseId':self.wh.pk,'plannedQty':10,'date':str(date.today()),'unitCost':1})
 def test_login_does_not_trust_role(self):
  get_user_model().objects.create_user(username='staff',password='Strong-test-238!',organization=self.org,role='cashier',branch=self.br)
  self.api.force_authenticate(None);d=self.post('auth/login/',{'username':'staff','password':'Strong-test-238!','role':'owner'},200)
  self.assertEqual(d['user']['role'],'cashier');self.assertNotIn('refresh',d);self.assertTrue(self.api.cookies['perfumosol_refresh']['httponly'])
 def test_refresh_origin_reload_logout(self):
  self.api.force_authenticate(None);self.post('auth/login/',{'username':'owner','password':'Strong-test-238!'},200);old=self.api.cookies['perfumosol_refresh'].value
  self.assertEqual(self.api.post('/api/v1/auth/token/refresh/',{},format='json',HTTP_ORIGIN='https://bad.example').status_code,403)
  r=self.api.post('/api/v1/auth/token/refresh/',{},format='json',HTTP_ORIGIN='http://localhost:5173');self.assertEqual(r.status_code,200);self.assertEqual(old,self.api.cookies['perfumosol_refresh'].value)
  self.post('auth/token/refresh/',{'refresh':old},200)
  self.assertEqual(self.api.post('/api/v1/auth/logout/',{},format='json',HTTP_ORIGIN='http://localhost:5173').status_code,200)
  self.post('auth/token/refresh/',{'refresh':old},401)
 def test_profile_password(self):
  r=self.api.patch('/api/v1/auth/profile/',{'name':'Hashif','bio':'Owner'},format='json');self.assertEqual(r.status_code,200)
  self.user.refresh_from_db();self.assertEqual(self.user.first_name,'Hashif');self.assertEqual(self.api.patch('/api/v1/auth/profile/',{'role':'owner'},format='json').status_code,400)
  self.post('auth/password/change/',{'currentPassword':'Strong-test-238!','newPassword':'Changed-pass-812!'},200);self.user.refresh_from_db();self.assertTrue(self.user.check_password('Changed-pass-812!'))
 def test_password_reset(self):
  from urllib.parse import urlparse,parse_qs
  self.api.force_authenticate(None);self.post('auth/password/reset/',{'email':'owner@example.com'},200);self.assertEqual(len(mail.outbox),1)
  q=parse_qs(urlparse(mail.outbox[0].body.split()[-1]).query);payload={'uid':q['uid'][0],'token':q['token'][0],'newPassword':'Reset-pass-882!'}
  self.post('auth/password/reset/confirm/',payload,200);self.post('auth/password/reset/confirm/',payload,400)
 def test_master_crud_filter_page(self):
  d=self.post('warehouses/',{'name':'Depot','code':'DP','location':'Calicut','manager':'Manager'})
  r=self.api.put('/api/v1/warehouses/'+d['id']+'/',{'name':'Updated depot','code':'DP','location':'Calicut','manager':'Manager'},format='json');self.assertEqual(r.status_code,200)
  self.assertEqual(self.get('warehouses/'+d['id']+'/')['name'],'Updated depot');self.assertEqual(len(self.get('warehouses/?search=Updated')),1);self.assertIn('results',self.get('warehouses/?page=1'))
  self.assertEqual(self.api.delete('/api/v1/warehouses/'+d['id']+'/').status_code,204)
 def test_tenant_isolation(self):
  mat=m.Material.objects.create(organization=self.other,name='Other oil',code='OIL',category='Perfume Oil')
  self.assertEqual(self.api.get('/api/v1/inventory/raw-materials/'+mat.pk+'/').status_code,404);self.post('fragrances/',{'name':'Bad','code':'BAD','perfumeOilId':mat.pk},400)
  self.assertNotIn(mat.pk,[r['id'] for r in self.get('inventory/raw-materials/')])
 def test_role_location_permissions(self):
  self.user.role='cashier';self.user.save();self.post('inventory/adjustments/',{'quantity':1},403)
  self.post('sales/pos/checkout/',{'branchId':self.br2.pk,'cart':[{'id':self.v.pk,'qty':1}]},403)
 def test_formula_costs(self):
  p=self.post('formulas/preview/',self.basis,200);self.assertEqual(p['oilQty'],10);self.assertEqual(p['solventQty'],40);self.assertEqual(p['estimatedUnitCost'],137)
  p=self.post('formulas/',{**self.basis,'estimatedUnitCost':1});self.assertEqual(p['estimatedUnitCost'],137);self.assertEqual(self.get('products/variants/'+self.v.pk+'/costing/')['liquidCost'],100)
 def test_variant_basis_validation(self):
  sz=m.BottleSize.objects.create(organization=self.org,name='30 ml',volumeMl=30,bottleMaterialRef=self.bot)
  self.post('products/variants/',{'productId':self.prod.pk,'fragranceId':self.fr.pk,'bottleSizeId':sz.pk,'concentrationId':self.conc.pk,'formulaId':self.form.pk,'sku':'BAD','sellingPrice':599,'minSellingPrice':500},400)
 def test_batch_snapshot_and_complete_once(self):
  b=self.batch();self.assertEqual(b['unitCost'],137);self.oil.currentCost=100;self.oil.save()
  out=self.post('production/batches/'+b['id']+'/complete/',{'actualProduced':10},200);self.assertEqual(out['unitCost'],137);self.assertEqual(self.balance(self.oil,self.wh),900);self.assertEqual(self.balance(self.v,self.wh),10)
  self.post('production/batches/'+b['id']+'/complete/',{'actualProduced':10},400);self.assertEqual(self.balance(self.v,self.wh),10)
  self.assertEqual(self.api.put('/api/v1/formulas/'+self.form.pk+'/',self.basis,format='json').status_code,400)
 def test_batch_rollback(self):
  b=self.batch();rows=[{**r,'actual':r['standard']} for r in b['standardConsumption']];rows[-1]['actual']=99999
  self.post('production/batches/'+b['id']+'/complete/',{'actualProduced':10,'actualConsumption':rows},400);self.assertEqual(self.balance(self.oil,self.wh),1000);self.assertEqual(m.Batch.objects.get(pk=b['id']).status,'Draft')
 def test_adjust_wastage_and_underflow(self):
  d={'itemId':self.oil.pk,'location':'Warehouse','itemType':'Raw Material','quantity':10,'adjustmentType':'subtract','reason':'Audit'};self.post('inventory/adjustments/',d);self.assertEqual(self.balance(self.oil,self.wh),990)
  w=self.post('inventory/wastage/',{'item':'Oil','location':'Warehouse','qty':2,'cost':1,'reason':'Spill','date':str(date.today())});self.assertEqual(w['cost'],16);self.assertEqual(self.balance(self.oil,self.wh),988)
  self.post('inventory/adjustments/',{**d,'quantity':9999},400);self.assertEqual(self.balance(self.oil,self.wh),988);self.assertEqual(self.api.delete('/api/v1/inventory/wastage/'+w['id']+'/').status_code,400)
 def test_transfer_lifecycle(self):
  t=self.post('transfers/',{'sourceName':'Branch','sourceType':'Branch','destName':'Other branch','destType':'Branch','items':[{'itemType':'Finished Product','itemId':self.v.pk,'requestedQty':5}]});base='transfers/'+t['id']+'/'
  self.post(base+'dispatch/',{},400);self.post(base+'approve/',{},200);self.post(base+'dispatch/',{},200);self.assertEqual(self.balance(self.v,self.br),15)
  self.post(base+'receive/',{'items':[{'itemId':self.v.pk,'receivedQty':4,'damagedQty':1}]},200);self.assertEqual(self.balance(self.v,self.br2),4);self.assertEqual(m.Transfer.objects.get(pk=t['id']).receivedBy,self.user);self.post(base+'receive/',{},400);self.post(base+'cancel/',{},400)
 def test_purchase_workflow(self):
  po=self.po();self.assertEqual(po['grandTotal'],199)
  grn={'poNumber':po['poNumber'],'deliveryNoteNo':'DN1','items':[{'material':'Oil','currentReceived':10,'acceptedQty':9,'rejectedQty':1,'unitCost':10}]};g=self.post('purchases/grn/',grn);self.assertEqual(g['status'],'Partial Receipt');self.assertEqual(self.balance(self.oil,self.wh),1009)
  self.post('purchases/grn/',{**grn,'deliveryNoteNo':'DN2','items':[{'material':'Oil','currentReceived':11,'acceptedQty':11,'rejectedQty':0}]},400)
  bill=self.post('purchases/bills/',{'supplierName':'Supplier','billNumber':'VENDOR1','linkedRef':po['poNumber'],'date':str(date.today()),'dueDate':str(date.today()),'amount':199,'paid':10})
  self.post('purchases/payments/',{'billId':bill['id'],'amount':100,'reference':'BANK-REF-1'});self.assertEqual(m.SupplierPayment.objects.get(bill_id=bill['id']).reference,'BANK-REF-1');self.assertEqual(self.get('purchases/bills/'+bill['id']+'/')['balance'],89);self.post('purchases/payments/',{'billId':bill['id'],'amount':100},400)
  r=self.post('purchases/returns/',{'supplierName':'Supplier','warehouseName':'Warehouse','material':'Oil','linkedRef':po['poNumber'],'qty':2,'reason':'Bad quality'});self.assertEqual(r['totalAmount'],20);self.assertEqual(self.balance(self.oil,self.wh),1007)
 def test_pos_authoritative_return(self):
  i=self.sale();self.assertEqual(i['total'],1198);self.assertEqual(i['items'][0]['costSnapshot'],137);self.assertEqual(self.balance(self.v,self.br),18)
  self.v.costPrice=300;self.v.save();d={'invoiceNumber':i['invoiceNumber'],'sku':'P50','qty':1,'condition':'Sellable','reason':'Exchange','refundAmount':99999}
  r=self.post('sales/returns/',d);self.assertEqual(r['refundAmount'],599);self.assertEqual(self.balance(self.v,self.br),19);self.post('sales/returns/',{**d,'qty':2},400);self.assertEqual(self.get('sales/invoices/'+i['id']+'/')['items'][0]['costSnapshot'],137)
 def test_pos_rollback_minimum_price(self):
  d={'branchId':self.br.pk,'cart':[{'id':self.v.pk,'qty':21}]};self.post('sales/pos/checkout/',d,400);self.assertEqual(m.Invoice.objects.count(),0);self.assertEqual(self.balance(self.v,self.br),20)
  self.post('sales/pos/checkout/',{**d,'cart':[{'id':self.v.pk,'qty':1}],'discount':100},400);self.assertEqual(m.Invoice.objects.count(),0)
 def test_expense_crud_balances(self):
  e=self.post('finance/expenses/',{'date':str(date.today()),'category':'Utilities','description':'Power','amount':30,'paymentMethod':'Cash'});self.assertEqual(self.get('finance/dashboard/')['cashBalance'],-30);self.assertEqual(e['createdBy'],'owner')
  r=self.api.patch('/api/v1/finance/expenses/'+e['id']+'/',{'amount':40},format='json');self.assertEqual(r.status_code,200);self.assertEqual(self.get('finance/dashboard/')['cashBalance'],-40);self.assertEqual(m.LedgerEntry.objects.count(),3)
  self.assertEqual(self.api.delete('/api/v1/finance/expenses/'+e['id']+'/').status_code,204);self.assertEqual(self.get('finance/dashboard/')['cashBalance'],0)
 def test_credit_settlement(self):
  c=self.post('customers/',{'name':'Customer','mobile':'9998887776'});i=self.sale(customerId=c['id'],paymentMethod='Credit');self.assertEqual(self.get('finance/receivables/')[0]['outstanding'],1198)
  r=self.api.patch('/api/v1/finance/receivables/'+i['id']+'/',{'outstanding':598},format='json');self.assertEqual(r.status_code,200);self.assertEqual(self.get('finance/dashboard/')['bankBalance'],600)
 def test_reports_actual_values(self):
  self.sale();self.post('finance/expenses/',{'date':str(date.today()),'category':'Utilities','description':'Power','amount':50})
  r=self.get('reports/summary/?fromDate='+str(date.today())+'&toDate='+str(date.today()));self.assertEqual(r['salesSummary']['totalRevenue'],1198);self.assertEqual(r['salesSummary']['cogs'],274);self.assertEqual(r['profitLoss']['netOperatingProfit'],874);self.assertEqual(self.get('reports/summary/?branch=Other%20branch')['salesSummary']['totalRevenue'],0)
 def test_all_major_read_endpoints(self):
  c=self.post('customers/',{'name':'New','mobile':'1234567890'})
  for url in ['warehouses/','branches/','suppliers/','customers/','inventory/raw-materials/','inventory/stock-overview/','inventory/movements/','inventory/adjustments/','inventory/wastage/','inventory/low-stock/','fragrances/','concentrations/','bottle-sizes/','formulas/','products/','products/variants/','production/batches/','transfers/','purchases/orders/','purchases/grn/','purchases/bills/','purchases/returns/','sales/invoices/','sales/returns/','finance/dashboard/','finance/cash-bank/','finance/income/','finance/expenses/','finance/receivables/','finance/payables/','reports/summary/','dashboard/summary/','dashboard/alerts/','suppliers/'+self.sup.pk+'/','customers/'+c['id']+'/']:
   with self.subTest(url=url): self.get(url)
 def test_health_unauthorized(self):
  self.assertEqual(self.api.get('/health/').status_code,200);self.api.force_authenticate(None);self.assertEqual(self.api.get('/api/v1/inventory/raw-materials/').status_code,401)

 def test_purchase_return_grn_and_reason_correction(self):
  po=self.po();g=self.post('purchases/grn/',{'poNumber':po['poNumber'],'deliveryNoteNo':'X','items':[{'material':'Oil','currentReceived':5,'acceptedQty':5,'rejectedQty':0}]})
  d={'supplierName':'Supplier','warehouseName':'Warehouse','material':'Oil','linkedRef':g['grnNumber'],'qty':2,'reason':'Damaged'}
  ret=self.post('purchases/returns/',d)
  response=self.api.patch('/api/v1/purchases/returns/'+ret['id']+'/',{'reason':'Quality rejection'},format='json');self.assertEqual(response.status_code,200,response.data)
  self.assertEqual(m.PurchaseReturn.objects.get(pk=ret['id']).reason,'Quality rejection')
  self.post('purchases/returns/',{**d,'qty':4},400)
 def test_purchase_order_edit_does_not_duplicate(self):
  po=self.po();d={'supplierName':'Supplier','warehouseName':'Warehouse','orderDate':str(date.today()),'expectedDate':str(date.today()),'items':[{'material':'Oil','qty':5,'rate':11}]}
  r=self.api.patch('/api/v1/purchases/orders/'+po['id']+'/',d,format='json');self.assertEqual(r.status_code,200,r.data);self.assertEqual(r.data['grandTotal'],55)
  self.assertEqual(m.PurchaseOrder.objects.count(),1);self.assertEqual(m.PurchaseLine.objects.count(),1)
  self.assertEqual(self.api.delete('/api/v1/purchases/orders/'+po['id']+'/').status_code,204)
 def test_cashier_catalog_and_stock_scope(self):
  self.user.role='cashier';self.user.save()
  for route in ['branches/','products/variants/','products/','customers/']: self.get(route)
  self.assertEqual(self.get('products/variants/')[0]['stock'],20)
  self.assertEqual(self.api.get('/api/v1/finance/dashboard/').status_code,403)

 def test_password_change_revokes_refresh(self):
  self.api.force_authenticate(None);self.post('auth/login/',{'username':'owner','password':'Strong-test-238!'},200)
  refresh=self.api.cookies['perfumosol_refresh'].value
  self.user.set_password('New-password-998!');self.user.save()
  self.post('auth/token/refresh/',{'refresh':refresh},401)
 def test_all_master_crud_roundtrips(self):
  resources=[('branches/',{'name':'Test branch','code':'TBR','warehouse':self.wh.pk}),('suppliers/',{'name':'Test supplier','code':'TSUP'}),('customers/',{'name':'Test customer','mobile':'99887766'}),('inventory/raw-materials/',{'name':'Test cap','code':'TCAP','category':'Cap','unit':'pcs','currentCost':1,'minStock':2}),('fragrances/',{'name':'Test fragrance','code':'TFR','perfumeOilId':self.oil.pk}),('concentrations/',{'name':'Test concentration','code':'TC','oilPercentage':25}),('bottle-sizes/',{'name':'Test size','volumeMl':30,'bottleMaterialRef':self.bot.pk}),('products/',{'name':'Test product','code':'TPROD'})]
  for url,payload in resources:
   with self.subTest(resource=url):
    obj=self.post(url,payload);endpoint='/api/v1/'+url+obj['id']+'/'
    result=self.api.patch(endpoint,{'name':payload['name']+' edited','status':'inactive'},format='json');self.assertEqual(result.status_code,200,result.data)
    self.assertEqual(self.get(url+obj['id']+'/')['status'],'inactive');self.assertEqual(self.api.delete(endpoint).status_code,204)
  self.assertEqual(self.api.delete('/api/v1/inventory/raw-materials/'+self.oil.pk+'/').status_code,409)
 def test_transfer_draft_edit_and_atomic_rejection(self):
  t=self.post('transfers/',{'sourceName':'Branch','sourceType':'Branch','destName':'Other branch','destType':'Branch','items':[{'itemType':'Finished Product','itemId':self.v.pk,'requestedQty':5}]});url='/api/v1/transfers/'+t['id']+'/'
  edited=self.api.patch(url,{'notes':'Edited draft','items':[{'itemType':'Finished Product','itemId':self.v.pk,'requestedQty':3}]},format='json');self.assertEqual(edited.status_code,200,edited.data)
  self.assertEqual(edited.data['id'],t['id']);self.assertEqual(edited.data['items'][0]['requestedQty'],3);self.assertEqual(self.balance(self.v,self.br),20)
  invalid=self.api.patch(url,{'items':[{'itemType':'Finished Product','itemId':self.v.pk,'requestedQty':999}]},format='json');self.assertEqual(invalid.status_code,400);self.assertEqual(m.Transfer.objects.count(),1)
  self.post('transfers/'+t['id']+'/approve/',{},200);self.assertEqual(self.api.patch(url,{'notes':'Too late'},format='json').status_code,400)
 def test_manual_ledger_reversal_retains_history(self):
  obj=self.post('finance/manual-income/',{'date':str(date.today()),'amount':12,'account':'Cash','type':'Inflow','reference':'INC-TEST','description':'Investment'})
  url='/api/v1/finance/transactions/'+obj['id']+'/'
  self.assertEqual(self.api.patch(url,{'amount':20},format='json').status_code,400);self.assertEqual(self.api.delete(url).status_code,400)
  self.post('finance/transactions/'+obj['id']+'/reverse/',{},200);self.assertTrue(m.LedgerEntry.objects.filter(pk=obj['id'],status='Reversed').exists())
  entries=m.LedgerEntry.objects.filter(sourceId=obj['id']);self.assertEqual(entries.count(),1);self.assertEqual(entries.first().amount,12)
  self.post('finance/transactions/'+obj['id']+'/reverse/',{},400)
  self.post('finance/manual-income/',{'date':str(date.today()),'amount':0,'account':'Cash','type':'Inflow','reference':'BAD','description':'Invalid'},400)
 def test_purchase_credit_consistent_across_projections(self):
  po=self.po();self.post('purchases/grn/',{'poNumber':po['poNumber'],'deliveryNoteNo':'CREDIT-GRN','items':[{'material':'Oil','currentReceived':10,'acceptedQty':10,'rejectedQty':0,'unitCost':10}]})
  bill=self.post('purchases/bills/',{'supplierName':'Supplier','billNumber':'CREDIT-BILL','linkedRef':po['poNumber'],'date':str(date.today()),'dueDate':str(date.today()),'amount':100})
  self.post('purchases/returns/',{'supplierName':'Supplier','warehouseName':'Warehouse','material':'Oil','linkedRef':po['poNumber'],'qty':2,'reason':'Quality'})
  self.assertEqual(self.get('purchases/bills/'+bill['id']+'/')['balance'],80)
  self.assertEqual(next(r for r in self.get('finance/payables/') if r['id']==bill['id'])['outstanding'],80)
  self.post('purchases/payments/',{'billId':bill['id'],'amount':81},400)
  self.post('purchases/payments/',{'billId':bill['id'],'amount':80});self.assertEqual(self.get('finance/payables/'),[])
 def test_warehouse_manager_cannot_delete_unassigned_location(self):
  self.user.role='warehouse_manager';self.user.save()
  self.assertEqual(self.api.delete('/api/v1/warehouses/'+self.br2.pk+'/').status_code,404)
  unassigned=m.Location.objects.create(organization=self.org,name='Unassigned',code='UN',kind='Warehouse')
  self.assertEqual(self.api.delete('/api/v1/warehouses/'+unassigned.pk+'/').status_code,403)
 def test_formula_variant_draft_crud_and_posted_restrictions(self):
  form=self.post('formulas/',{**self.basis,'version':'editable','packaging':[{'materialId':self.bot.pk,'qty':2}]});url='/api/v1/formulas/'+form['id']+'/'
  updated=self.api.patch(url,{**self.basis,'version':'edited','packaging':[{'materialId':self.bot.pk,'qty':3}]},format='json');self.assertEqual(updated.status_code,200,updated.data);self.assertEqual(updated.data['packaging'][0]['qty'],3)
  variant=self.post('products/variants/',{'name':'Test variant','productId':self.prod.pk,'fragranceId':self.fr.pk,'bottleSizeId':self.size.pk,'concentrationId':self.conc.pk,'formulaId':form['id'],'sku':'TEST-SKU','sellingPrice':599,'minSellingPrice':500,'mrp':699})
  variant_url='/api/v1/products/variants/'+variant['id']+'/'
  self.assertEqual(self.api.patch(variant_url,{'sellingPrice':600,'status':'inactive'},format='json').status_code,200)
  self.assertEqual(self.api.delete(url).status_code,409);self.assertEqual(m.Formula.objects.get(pk=form['id']).lines.count(),3)
  self.assertEqual(self.api.delete(variant_url).status_code,204);self.assertEqual(self.api.delete(url).status_code,204)
  batch=self.batch();burl='/api/v1/production/batches/'+batch['id']+'/'
  self.assertEqual(self.api.patch(burl,{'plannedQty':2,'notes':'Edited draft'},format='json').status_code,200);self.assertEqual(self.api.delete(burl).status_code,204)
  invoice=self.sale();iurl='/api/v1/sales/invoices/'+invoice['id']+'/'
  self.assertEqual(self.api.patch(iurl,{'customerName':'Corrected name'},format='json').status_code,200);self.assertEqual(self.api.delete(iurl).status_code,400)
 def test_packaging_invalid_inputs(self):
  for rows in [[{'materialId':self.oil.pk,'qty':1}],[{'materialId':self.bot.pk,'qty':0}],[{'materialId':self.bot.pk,'qty':1},{'materialId':self.bot.pk,'qty':1}]]:
   self.post('formulas/',{**self.basis,'packaging':rows},400)
 def test_checkout_request_retries_do_not_post_twice(self):
  payload={'branchId':self.br.pk,'cart':[{'id':self.v.pk,'qty':1}],'checkoutKey':'request-key-1','paymentMethod':'Cash'}
  first=self.post('sales/pos/checkout/',payload)['invoice'];second=self.post('sales/pos/checkout/',payload)['invoice']
  self.assertEqual(first['id'],second['id']);self.assertEqual(m.Invoice.objects.count(),1);self.assertEqual(self.balance(self.v,self.br),19)
  self.assertEqual(m.Movement.objects.filter(reference=first['invoiceNumber']).count(),1)
  self.post('sales/pos/checkout/',{**payload,'cart':[{'id':self.v.pk,'qty':2}]},400)
