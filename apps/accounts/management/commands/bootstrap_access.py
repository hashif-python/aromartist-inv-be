from importlib import import_module
from django.apps import apps
from django.core.management.base import BaseCommand
class Command(BaseCommand):
 help='Create missing starter roles and migrate unassigned legacy users without changing existing role definitions.'
 def handle(self,*args,**kwargs):
  import_module('apps.accounts.migrations.0004_seed_access_roles').seed(apps,None)
  import_module('apps.accounts.migrations.0006_seed_permission_catalog').seed(apps,None)
  self.stdout.write('Starter roles ready; existing role definitions and assignments preserved.')
