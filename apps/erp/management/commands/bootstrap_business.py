from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.db import transaction
from apps.accounts.models import Organization
class Command(BaseCommand):
 help='Assign an existing superuser to an organization; does not reset any data.'
 def add_arguments(self,parser):
  parser.add_argument('--username',required=True);parser.add_argument('--name',default='Aromartist Perfume')
 @transaction.atomic
 def handle(self,*args,**opts):
  try: u=get_user_model().objects.get(username=opts['username'],is_superuser=True)
  except get_user_model().DoesNotExist: raise CommandError('Create this Django superuser first.')
  from apps.erp.category_utils import ensure_base_categories
  if u.organization_id:
   ensure_base_categories(u.organization)
   self.stdout.write(f'Already assigned to {u.organization}. No changes.');return
  org,_=Organization.objects.get_or_create(name=opts['name']);u.organization=org;u.role='owner';u.save()
  ensure_base_categories(org)
  self.stdout.write(self.style.SUCCESS('Organization assignment complete.'))
