from django.db import migrations

def create_categories(apps,schema_editor):
    Organization=apps.get_model('accounts','Organization');Category=apps.get_model('erp','MaterialCategory')
    db=schema_editor.connection.alias
    for org in Organization.objects.using(db).all():
        for name,kind,unit in [('Oil','Perfume Oil','ml'),('Solvent','Solvent','ml'),('Packaging','Packaging','pcs'),('Others','Other','pcs')]:
            Category.objects.using(db).get_or_create(organization_id=org.pk,name=name,defaults={'categoryType':kind,'unit':unit,'description':'Main stock category.'})
class Migration(migrations.Migration):
    dependencies=[('erp','0017_bottlesize_diptubematerialref_and_more')]
    operations=[migrations.RunPython(create_categories,migrations.RunPython.noop)]
