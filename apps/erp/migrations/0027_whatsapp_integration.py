from django.db import migrations, models
import django.db.models.deletion
import apps.erp.models

class Migration(migrations.Migration):
    dependencies=[('erp','0026_invoice_gst_details')]
    operations=[
        migrations.CreateModel(name='WhatsAppConnection',fields=[
            ('id',models.CharField(primary_key=True,max_length=40,default=apps.erp.models.uid,editable=False,serialize=False)),
            ('created_at',models.DateTimeField(auto_now_add=True)),('updated_at',models.DateTimeField(auto_now=True)),
            ('instance_name',models.CharField(max_length=100,unique=True)),('auto_send',models.BooleanField(default=False)),
            ('organization',models.ForeignKey(to='accounts.organization',on_delete=django.db.models.deletion.PROTECT)),
        ],options={'constraints':[models.UniqueConstraint(fields=['organization'],name='one_whatsapp_connection_per_org')]}),
        migrations.CreateModel(name='WhatsAppInvoiceDelivery',fields=[
            ('id',models.CharField(primary_key=True,max_length=40,default=apps.erp.models.uid,editable=False,serialize=False)),
            ('created_at',models.DateTimeField(auto_now_add=True)),('updated_at',models.DateTimeField(auto_now=True)),
            ('phone',models.CharField(max_length=32)),('status',models.CharField(max_length=20,default='pending')),
            ('provider_message_id',models.CharField(max_length=160,blank=True)),('error',models.TextField(blank=True)),
            ('sent_at',models.DateTimeField(null=True,blank=True)),
            ('organization',models.ForeignKey(to='accounts.organization',on_delete=django.db.models.deletion.PROTECT)),
            ('invoice',models.ForeignKey(to='erp.invoice',related_name='whatsapp_deliveries',on_delete=django.db.models.deletion.PROTECT)),
        ])
    ]
