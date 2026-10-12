from . import models as m
LEGACY_TYPES={'Perfume Oil':'Perfume Oil','Solvent':'Solvent','Bottle':'Packaging','Packaging':'Packaging','Dip Tube':'Packaging','Atomizer':'Packaging','Pump':'Packaging','Cap':'Packaging','Label':'Packaging','Pouch':'Packaging','Carry Bag':'Packaging','Carton':'Packaging'}
def material_type(material):
    return material.categoryRef.categoryType if material.categoryRef_id else LEGACY_TYPES.get(material.category,'Other')
def register_existing_categories(org):
    for mat in m.Material.objects.filter(organization=org,categoryRef__isnull=True).order_by('created_at'):
        name=mat.category
        existing=m.MaterialCategory.objects.filter(organization=org,name=name).first()
        if existing and existing.unit!=mat.unit: name=f'{name} ({mat.unit})'
        category,_=m.MaterialCategory.objects.get_or_create(organization=org,name=name,defaults={'categoryType':LEGACY_TYPES.get(mat.category,'Other'),'unit':mat.unit,'description':'Imported from existing material categories.'})
        mat.categoryRef=category;mat.category=category.name;mat.save(update_fields=['categoryRef','category'])

def ensure_base_categories(org):
    for name,kind,unit in [('Oil','Perfume Oil','ml'),('Solvent','Solvent','ml'),('Packaging','Packaging','pcs'),('Others','Other','pcs')]:
        m.MaterialCategory.objects.get_or_create(organization=org,name=name,defaults={'categoryType':kind,'unit':unit,'description':'Main stock category. Packaging includes bottles, caps, pumps and separate dip tubes.' if kind=='Packaging' else 'Main stock category.'})


def packaging_type(material):
    if material.packagingType:return material.packagingType
    return material.category if material.category in {'Bottle','Pump','Cap','Label','Dip Tube'} else 'Pump' if material.category=='Atomizer' else ''
