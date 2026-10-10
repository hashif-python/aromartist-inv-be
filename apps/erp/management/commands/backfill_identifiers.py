from django.core.management.base import BaseCommand,CommandError
from django.apps import apps
from django.db import transaction
from apps.accounts.models import Organization
from apps.common.services.code_generator import FIELDS,config_for,generate_for

class Command(BaseCommand):
 help='Dry-run or fill only empty registered identifiers, preserving every existing value.'
 def add_arguments(self,parser):
  parser.add_argument('--organization-id',type=int,required=True)
  parser.add_argument('--apply',action='store_true')
 def handle(self,*args,**options):
  try:org=Organization.objects.get(pk=options['organization_id'])
  except Organization.DoesNotExist:raise CommandError('Organization does not exist.')
  keys=list(FIELDS)+[('erp','location'),('erp','ledgerentry')]
  total=0
  for app,name in keys:
   model=apps.get_model(app,name)
   with transaction.atomic():
    Organization.objects.select_for_update().get(pk=org.pk)
    for obj in model.objects.filter(organization=org).order_by('created_at').iterator():
     cfg=config_for(obj)
     if not cfg or getattr(obj,cfg[0]):continue
     total+=1
     if options['apply']:
      generate_for(obj);obj.save(update_fields=[cfg[0]])
     self.stdout.write(f'{model._meta.label} {obj.pk}: {getattr(obj,cfg[0]) or "would allocate"}')
  self.stdout.write(f'{total} empty identifiers '+('filled.' if options['apply'] else 'found. Use --apply to fill.'))
