from django.db import migrations,models
import django.db.models.deletion
import apps.erp.models

class Migration(migrations.Migration):
    initial=True
    dependencies=[('erp','0026_invoice_gst_details'),('accounts','0007_organization_defaultbranch_and_more')]
    operations=[
        migrations.CreateModel(name='Offer',fields=[
            ('id',models.CharField(primary_key=True,max_length=40,default=apps.erp.models.uid,editable=False,serialize=False)),
            ('created_at',models.DateTimeField(auto_now_add=True)),('updated_at',models.DateTimeField(auto_now=True)),
            ('name',models.CharField(max_length=160)),('code',models.CharField(max_length=50)),('description',models.TextField(blank=True)),
            ('offer_type',models.CharField(max_length=40,choices=[('BUY_X_GET_Y','Buy X Get Y'),('PERCENTAGE_DISCOUNT','Percentage discount'),('FIXED_DISCOUNT','Fixed discount')])),
            ('status',models.CharField(max_length=12,default='draft',choices=[('draft','Draft'),('active','Active'),('paused','Paused'),('archived','Archived')])),
            ('starts_at',models.DateTimeField(null=True,blank=True)),('ends_at',models.DateTimeField(null=True,blank=True)),
            ('buy_quantity',models.PositiveIntegerField(default=1)),('get_quantity',models.PositiveIntegerField(default=1)),
            ('discount_percentage',models.DecimalField(max_digits=6,decimal_places=2,default=0)),
            ('discount_amount',models.DecimalField(max_digits=18,decimal_places=4,default=0)),
            ('repeatable',models.BooleanField(default=True)),('automatic',models.BooleanField(default=True)),('priority',models.IntegerField(default=0)),
            ('organization',models.ForeignKey(to='accounts.organization',on_delete=django.db.models.deletion.PROTECT)),
            ('products',models.ManyToManyField(to='erp.product',blank=True,related_name='offers')),
            ('branches',models.ManyToManyField(to='erp.location',blank=True,related_name='offers')),
        ]),
        migrations.CreateModel(name='Redemption',fields=[
            ('id',models.CharField(primary_key=True,max_length=40,default=apps.erp.models.uid,editable=False,serialize=False)),
            ('created_at',models.DateTimeField(auto_now_add=True)),('updated_at',models.DateTimeField(auto_now=True)),
            ('discount',models.DecimalField(max_digits=18,decimal_places=4,default=0)),('snapshot',models.JSONField(default=dict)),
            ('organization',models.ForeignKey(to='accounts.organization',on_delete=django.db.models.deletion.PROTECT)),
            ('offer',models.ForeignKey(to='promotions.offer',on_delete=django.db.models.deletion.PROTECT)),
            ('invoice',models.ForeignKey(to='erp.invoice',on_delete=django.db.models.deletion.PROTECT,related_name='offer_redemptions')),
        ]),
        migrations.AddConstraint(model_name='offer',constraint=models.UniqueConstraint(fields=['organization','code'],name='promotion_code_org')),
        migrations.AddConstraint(model_name='redemption',constraint=models.UniqueConstraint(fields=['offer','invoice'],name='promotion_once_per_invoice')),
    ]
