from django.db import migrations, models

def move_type(apps, schema_editor):
    Material = apps.get_model('erp', 'Material')
    db = schema_editor.connection.alias
    legacy = {'Perfume Oil':'Perfume Oil','Solvent':'Solvent','Bottle':'Packaging','Packaging':'Packaging','Dip Tube':'Packaging','Atomizer':'Packaging','Pump':'Packaging','Cap':'Packaging','Label':'Packaging','Pouch':'Packaging','Carry Bag':'Packaging','Carton':'Packaging'}
    for row in Material.objects.using(db).select_related('categoryRef').iterator():
        row.materialType = row.categoryRef.categoryType if row.categoryRef_id else legacy.get(row.category, 'Other')
        row.save(using=db, update_fields=['materialType'])

class Migration(migrations.Migration):
    dependencies = [('erp','0026_invoice_gst_details')]
    operations = [
        migrations.AddField(model_name='material', name='materialType', field=models.CharField(max_length=20, default='Other', choices=[('Perfume Oil','Perfume Oil'),('Solvent','Solvent'),('Packaging','Packaging'),('Other','Others')])),
        migrations.RunPython(move_type),
        migrations.RemoveField(model_name='materialcategory', name='categoryType'),
        migrations.RemoveField(model_name='materialcategory', name='unit'),
    ]
