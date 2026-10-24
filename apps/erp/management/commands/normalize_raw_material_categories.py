from django.core.management.base import BaseCommand
from django.db import transaction
from apps.accounts.models import Organization
from apps.erp.models import Material, MaterialCategory
from apps.erp.category_utils import material_type, packaging_type

KINDS = {
    "Perfume Oil": ("Oil", "Perfume Oil", "ml"),
    "Solvent": ("Solvent", "Solvent", "ml"),
    "Packaging": ("Packaging", "Packaging", "pcs"),
}
SUBTYPES = {"Bottle", "Cap", "Pump", "Label", "Dip Tube", "Other"}

class Command(BaseCommand):
    help = "Preview or normalize existing raw material categories without modifying stock quantities."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write changes (default is preview only)")
        parser.add_argument("--organization-id", help="Restrict to one organization ID")

    def handle(self, *args, **options):
        organizations = Organization.objects.all()
        if options["organization_id"]:
            organizations = organizations.filter(pk=options["organization_id"])
        count = 0
        with transaction.atomic():
            for org in organizations:
                categories = {}
                for kind, (name, category_type, unit) in KINDS.items():
                    if options["apply"]:
                        cat, _ = MaterialCategory.objects.get_or_create(
                            organization=org, name=name,
                            defaults={"categoryType": category_type, "unit": unit, "status": "active"},
                        )
                        if cat.categoryType != category_type or cat.unit != unit:
                            raise ValueError(f"Existing category {name} has conflicting type/unit; resolve manually.")
                        categories[kind] = cat
                for material in Material.objects.filter(organization=org).select_related("categoryRef"):
                    kind = material_type(material)
                    if kind not in KINDS:
                        self.stdout.write(f"SKIP {material.name}: unknown type {kind}")
                        continue
                    name, _, unit = KINDS[kind]
                    if material.unit != unit:
                        self.stdout.write(f"SKIP {material.name}: unit {material.unit} incompatible with {name} ({unit})")
                        continue
                    subtype = packaging_type(material) if kind == "Packaging" else ""
                    if kind == "Packaging" and subtype not in SUBTYPES:
                        subtype = "Other"
                    changed = material.category != name or material.packagingType != subtype or (
                        options["apply"] and material.categoryRef_id != categories[kind].pk
                    )
                    if changed:
                        count += 1
                        self.stdout.write(f"{'UPDATE' if options['apply'] else 'WOULD UPDATE'} {material.name} -> {name}/{subtype or '-'}")
                        if options["apply"]:
                            material.categoryRef = categories[kind]
                            material.category = name
                            material.packagingType = subtype
                            material.save(update_fields=["categoryRef", "category", "packagingType"])
            self.stdout.write(self.style.SUCCESS(f"{count} materials {'updated' if options['apply'] else 'eligible for update'}. Stock unchanged."))
