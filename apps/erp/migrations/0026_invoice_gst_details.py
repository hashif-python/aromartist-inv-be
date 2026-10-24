from django.db import migrations, models
import decimal

class Migration(migrations.Migration):
    dependencies=[('erp','0025_remove_fragrance_olfactoryfamily_and_more')]
    operations=[
        migrations.AddField(model_name='invoice',name='gstRate',field=models.DecimalField(max_digits=5,decimal_places=2,default=0)),
        *[migrations.AddField(model_name='invoice',name=name,field=models.DecimalField(max_digits=18,decimal_places=4,default=decimal.Decimal('0'))) for name in ['taxableAmount','cgst','sgst','igst']],
    ]
