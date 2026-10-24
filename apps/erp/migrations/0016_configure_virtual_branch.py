from django.db import migrations

def configure(apps,schema_editor):
    Location=apps.get_model('erp','Location');Stock=apps.get_model('erp','Stock')
    for branch in Location.objects.filter(kind='Branch',code__iexact='BR03'):
        targets=Location.objects.filter(organization_id=branch.organization_id,kind='Branch',code__in=['BR01','BR02'],status='active')
        if targets.count()==2 and not Stock.objects.filter(location=branch).exists():
            branch.isVirtual=True;branch.save(update_fields=['isVirtual']);branch.physicalBranches.set(targets)
class Migration(migrations.Migration):
    dependencies=[('erp','0015_invoiceline_product_invoiceline_recipesnapshot_and_more')]
    operations=[migrations.RunPython(configure,migrations.RunPython.noop)]
