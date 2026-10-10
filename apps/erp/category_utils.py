from . import models as m
LEGACY_TYPES={'Perfume Oil':'Perfume Oil','Solvent':'Solvent','Bottle':'Packaging','Packaging':'Packaging','Pump':'Packaging','Cap':'Packaging','Label':'Packaging','Pouch':'Packaging','Carry Bag':'Packaging','Carton':'Packaging'}
def material_type(material):
    return material.categoryRef.categoryType if material.categoryRef_id else LEGACY_TYPES.get(material.category,'Other')
def register_existing_categories(org):
    for mat in m.Material.objects.filter(organization=org,categoryRef__isnull=True).order_by('created_at'):
        name=mat.category
        existing=m.MaterialCategory.objects.filter(organization=org,name=name).first()
        if existing and existing.unit!=mat.unit: name=f'{name} ({mat.unit})'
        category,_=m.MaterialCategory.objects.get_or_create(organization=org,name=name,defaults={'categoryType':LEGACY_TYPES.get(mat.category,'Other'),'unit':mat.unit,'description':'Imported from existing material categories.'})
        mat.categoryRef=category;mat.category=category.name;mat.save(update_fields=['categoryRef','category'])
