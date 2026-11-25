from django.db import migrations, models
import django.db.models.deletion
import apps.erp.models

class Migration(migrations.Migration):
    dependencies=[('erp','0029_merge_category_fragrance')]
    operations=[
        migrations.CreateModel(name='MaterialSubcategory',fields=[
            ('id',models.CharField(primary_key=True,max_length=40,default=apps.erp.models.uid,editable=False,serialize=False)),
            ('created_at',models.DateTimeField(auto_now_add=True)),('updated_at',models.DateTimeField(auto_now=True)),
            ('name',models.CharField(max_length=160)),('status',models.CharField(max_length=20,choices=[('active','Active'),('inactive','Inactive')],default='active')),
            ('unit',models.CharField(max_length=10,choices=[('ml','ml'),('pcs','pcs'),('g','g'),('kg','kg'),('L','L')])),('description',models.TextField(blank=True)),
            ('organization',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,to='accounts.organization')),
            ('parent',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name='subcategories',to='erp.materialcategory')),
        ],options={'constraints':[models.UniqueConstraint(fields=['parent','name'],name='material_subcategory_name')]}),
        migrations.AddField(model_name='material',name='subcategoryRef',field=models.ForeignKey(null=True,blank=True,on_delete=django.db.models.deletion.PROTECT,related_name='materials',to='erp.materialsubcategory')),
    ]
