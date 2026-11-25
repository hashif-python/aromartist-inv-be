from django.db import migrations

FIELDS = ('defaultBottleSize', 'defaultOilPercentage', 'defaultType', 'solventRecipe')

def remove_existing(apps, schema_editor):
    model = apps.get_model('erp', 'Fragrance')
    with schema_editor.connection.cursor() as cursor:
        columns = {c.name for c in schema_editor.connection.introspection.get_table_description(cursor, model._meta.db_table)}
    for name in FIELDS:
        field = model._meta.get_field(name)
        if field.column in columns:
            if schema_editor.connection.vendor == "postgresql":
                schema_editor.execute("ALTER TABLE %s DROP COLUMN %s" % (schema_editor.quote_name(model._meta.db_table), schema_editor.quote_name(field.column)))
            else:
                schema_editor.remove_field(model, field)

class Migration(migrations.Migration):
    dependencies = [('erp', '0028_material_subcategories')]
    operations = [migrations.SeparateDatabaseAndState(
        database_operations=[migrations.RunPython(remove_existing)],
        state_operations=[migrations.RemoveField(model_name='fragrance', name=name) for name in FIELDS],
    )]
