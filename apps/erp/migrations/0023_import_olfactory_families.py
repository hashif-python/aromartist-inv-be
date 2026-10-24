from django.db import migrations

def import_families(apps,schema_editor):
    Family=apps.get_model('erp','OlfactoryFamily');Fragrance=apps.get_model('erp','Fragrance');db=schema_editor.connection.alias
    for fragrance in Fragrance.objects.using(db).exclude(category='').filter(olfactoryFamily=None):
        name=' '.join(fragrance.category.split())
        if not name:continue
        family=Family.objects.using(db).filter(organization_id=fragrance.organization_id,name__iexact=name).first()
        if not family:family=Family.objects.using(db).create(organization_id=fragrance.organization_id,name=name)
        Fragrance.objects.using(db).filter(pk=fragrance.pk).update(olfactoryFamily_id=family.pk,category=family.name)
class Migration(migrations.Migration):
    dependencies=[('erp','0022_location_ownerbranch_olfactoryfamily_and_more')]
    operations=[migrations.RunPython(import_families,migrations.RunPython.noop)]
