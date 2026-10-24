from collections import defaultdict
from django.db import migrations

def classify(apps,schema_editor):
    Material=apps.get_model('erp','Material');Bottle=apps.get_model('erp','BottleSize');db=schema_editor.connection.alias
    roles=defaultdict(set)
    for bottle in Bottle.objects.using(db).all():
        for field,kind in [('bottleMaterialRef','Bottle'),('pumpMaterialRef','Pump'),('capMaterialRef','Cap'),('labelMaterialRef','Label'),('dipTubeMaterialRef','Dip Tube')]:
            key=getattr(bottle,field+'_id')
            if key:roles[key].add(kind)
    Product=apps.get_model('erp','Product')
    for product in Product.objects.using(db).all():
        for row in product.packagingRecipe:
            role={'Pump / atomizer':'Pump','Dip tube':'Dip Tube'}.get(row.get('role'),row.get('role'))
            if row.get('materialId') and role in {'Bottle','Pump','Cap','Label','Dip Tube'}:roles[row['materialId']].add(role)
    known={'Bottle','Pump','Cap','Label','Dip Tube'}
    for material in Material.objects.using(db).select_related('categoryRef').all():
        if material.packagingType:continue
        if material.category in known:roles[material.pk].add(material.category)
        elif material.category=='Atomizer':roles[material.pk].add('Pump')
        if len(roles[material.pk])==1:
            Material.objects.using(db).filter(pk=material.pk).update(packagingType=next(iter(roles[material.pk])))
        elif not roles[material.pk] and material.categoryRef_id and material.categoryRef.categoryType=='Packaging':
            Material.objects.using(db).filter(pk=material.pk).update(packagingType='Other')
class Migration(migrations.Migration):
    dependencies=[('erp','0019_bottlesize_labelmaterialref_material_packagingtype')]
    operations=[migrations.RunPython(classify,migrations.RunPython.noop)]
