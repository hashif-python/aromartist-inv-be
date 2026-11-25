from . import models as m
LEGACY_TYPES={'Perfume Oil':'Perfume Oil','Solvent':'Solvent','Bottle':'Packaging','Packaging':'Packaging','Dip Tube':'Packaging','Atomizer':'Packaging','Pump':'Packaging','Cap':'Packaging','Label':'Packaging','Pouch':'Packaging','Carry Bag':'Packaging','Carton':'Packaging'}
def classification(category, subcategory=None):
    if subcategory:
        role = category_role(subcategory.name)
        if role in ('Perfume Oil', 'Solvent'):
            return role
    return category_role(category.name) if category else 'Other'

def material_type(material):
    if getattr(material, 'subcategoryRef_id', None):
        return classification(material.categoryRef, material.subcategoryRef)
    return LEGACY_TYPES.get(material.category, material.materialType) if not material.categoryRef_id and material.materialType == 'Other' else material.materialType

def active_ingredient(material):
    return (material.status == 'active' and material.unit == 'ml'
            and (not material.categoryRef_id or material.categoryRef.status == 'active')
            and (not getattr(material, 'subcategoryRef_id', None) or material.subcategoryRef.status == 'active'))

def register_existing_categories(org):
    for mat in m.Material.objects.filter(organization=org,categoryRef__isnull=True):
        category,_=m.MaterialCategory.objects.get_or_create(organization=org,name=mat.category)
        mat.categoryRef=category
        mat.materialType=LEGACY_TYPES.get(mat.category,'Other')
        mat.save(update_fields=['categoryRef','materialType'])

def ensure_base_categories(org):
    # Categories are user-defined; do not seed defaults.
    return None

def packaging_type(material):
    if material.packagingType:return material.packagingType
    return material.category if material.category in {'Bottle','Pump','Cap','Label','Dip Tube'} else 'Pump' if material.category=='Atomizer' else ''


def category_role(name):
    key=" ".join(name.strip().casefold().split())
    if key in {"oil", "oils", "perfume oil", "perfume oils", "fragrance oil", "fragrance oils"}: return "Perfume Oil"
    if key in {"solvent", "solvents"}: return "Solvent"
    if key in {"packaging", "packing", "packging", "packaging items", "bottle", "pump", "cap"}: return "Packaging"
    return "Other"
