from django.db import migrations
TYPES={'Perfume Oil':'Perfume Oil','Solvent':'Solvent','Packaging':'Packaging','Bottle':'Packaging','Pump':'Packaging','Cap':'Packaging','Label':'Packaging','Pouch':'Packaging','Carry Bag':'Packaging','Carton':'Packaging'}
def forwards(apps,schema_editor):
 Material=apps.get_model('erp','Material');Category=apps.get_model('erp','MaterialCategory');alias=schema_editor.connection.alias
 for mat in Material.objects.using(alias).all().iterator():
  name=mat.category
  existing=Category.objects.using(alias).filter(organization_id=mat.organization_id,name=name).first()
  if existing and existing.unit!=mat.unit:name=f'{name} ({mat.unit})'
  category,_=Category.objects.using(alias).get_or_create(organization_id=mat.organization_id,name=name,defaults={'categoryType':TYPES.get(mat.category,'Other'),'unit':mat.unit,'description':'Imported existing material category; stock and units preserved.'})
  Material.objects.using(alias).filter(pk=mat.pk).update(categoryRef_id=category.pk,category=category.name)
class Migration(migrations.Migration):
 dependencies=[('erp','0008_alter_material_category_materialcategory_and_more')]
 operations=[migrations.RunPython(forwards,migrations.RunPython.noop)]
