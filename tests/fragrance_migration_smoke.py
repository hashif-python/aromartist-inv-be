"""Run with python -m tests.fragrance_migration_smoke; uses its own temporary DB."""
import os,tempfile
from decimal import Decimal
from datetime import date

def main():
    with tempfile.TemporaryDirectory(prefix='fragrance-migration-') as directory:
        os.environ['DJANGO_SETTINGS_MODULE']='config.settings.test'
        os.environ['SQLITE_TEST_DATABASE']=os.path.join(directory,'migration.sqlite3')
        import django
        django.setup()
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor
        before=[('erp','0027_whatsapp_integration')];after=[('erp','0028_fragrance_defaults_knots')]
        executor=MigrationExecutor(connection);executor.migrate(before)
        apps=executor.loader.project_state(before).apps
        Org=apps.get_model('accounts','Organization');User=apps.get_model('accounts','User')
        org=Org.objects.create(name='Migration preservation');user=User.objects.create(username='migration-admin',organization=org,password='preserved-hash',is_superuser=True,is_staff=True)
        Location=apps.get_model('erp','Location');branch=Location.objects.create(organization=org,name='Main',code='BR01',kind='Branch')
        Material=apps.get_model('erp','Material');material=Material.objects.create(organization=org,name='Oil',code='OIL',category='Perfume Oil',unit='ml')
        Fragrance=apps.get_model('erp','Fragrance');fragrance=Fragrance.objects.create(organization=org,name='Legacy scent',code='F',perfumeOilId=material,pricesByType={'EDP':'800'})
        Product=apps.get_model('erp','Product');product=Product.objects.create(organization=org,name='Legacy perfume',code='PROD',recipe=[{'materialId':material.pk,'percentage':'20'}],directBlend=True,fillVolumeMl=100,sellingPrice=800)
        Stock=apps.get_model('erp','Stock');stock=Stock.objects.create(organization=org,location=branch,material=material,quantity=Decimal('456.7890'))
        Invoice=apps.get_model('erp','Invoice');invoice=Invoice.objects.create(organization=org,invoiceNumber='HIST-1',branch=branch,salesperson=user,customerName='Historic customer',date=date(2026,10,1),paymentMethod='Cash',subtotal=800,total=840,tax=40,gstRate=5,taxableAmount=800,cgst=20,sgst=20)
        executor=MigrationExecutor(connection);executor.migrate(after);apps=executor.loader.project_state(after).apps
        assert apps.get_model('accounts','User').objects.get(pk=user.pk).password=='preserved-hash'
        saved=apps.get_model('erp','Invoice').objects.get(pk=invoice.pk)
        assert (saved.total,saved.gstRate,saved.taxableAmount,saved.cgst,saved.sgst)==(840,5,800,20,20)
        p=apps.get_model('erp','Product').objects.get(pk=product.pk);assert not p.fragranceFirst and p.blendConfig=={} and p.recipe==product.recipe
        f=apps.get_model('erp','Fragrance').objects.get(pk=fragrance.pk);assert f.defaultType=='' and f.defaultOilPercentage is None and f.pricesByType=={'EDP':'800'}
        assert apps.get_model('erp','Stock').objects.get(pk=stock.pk).quantity==Decimal('456.7890')
        print('PASS: additive migration preserves admin hash, legacy product/recipe/prices, stock and historical GST invoice values.')
if __name__=='__main__':main()
