"""Explicit database reset with a preserved admin and a single stock warehouse."""
from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand,CommandError
from django.db import transaction
from apps.accounts.models import Organization,Role,UserRoleAssignment,UserBranchAssignment,PermissionAuditLog
from apps.erp import models as m

class Command(BaseCommand):
 help='DELETE operational data and all other accounts; preserve the selected admin/password and required settings; create one branch/warehouse. Back up first.'
 def add_arguments(self,p):
  p.add_argument('--username',required=True)
  p.add_argument('--confirm-reset',required=True,help='Must equal RESET-ALL-DATA')
  p.add_argument('--branch-name',default='Main Branch');p.add_argument('--warehouse-name',default='Main Warehouse')
 @transaction.atomic
 def handle(self,*args,**opts):
  if opts['confirm_reset']!='RESET-ALL-DATA':raise CommandError('No data changed. Supply --confirm-reset RESET-ALL-DATA only after backing up the database.')
  User=get_user_model()
  try:admin=User.objects.select_for_update().get(username=opts['username'])
  except User.DoesNotExist:raise CommandError('Admin account was not found. No data changed.')
  if not (admin.is_superuser or (admin.is_staff and admin.role=='owner')):raise CommandError('Select an existing admin/superuser account. No data changed.')
  org=admin.organization or Organization.objects.create(name='Aromartist')
  org=Organization.objects.select_for_update().get(pk=org.pk)
  # Break location references before removing operational models; preserve credentials/settings.
  Organization.objects.update(defaultBranch=None,defaultWarehouse=None,singleLocationMode=False)
  User.objects.update(branch=None,warehouse=None)
  UserBranchAssignment.objects.all().delete();UserRoleAssignment.objects.all().delete();PermissionAuditLog.objects.all().delete()
  operational=[model for model in apps.get_models(include_auto_created=True) if model._meta.app_label in {'erp','hrms','pos'} and model._meta.managed]
  # Reverse FK dependency order. Self-references are deleted together in a single statement.
  pending=set(operational);ordered=[]
  while pending:
   leaves=[parent for parent in pending if not any(child is not parent and any(f.is_relation and getattr(f,'related_model',None) is parent and (f.many_to_one or f.one_to_one) for f in child._meta.local_fields) for child in pending)]
   if not leaves:raise CommandError('Operational dependency cycle found; reset aborted and rolled back.')
   for model in sorted(leaves,key=lambda model:model._meta.label_lower):ordered.append(model);pending.remove(model)
  for model in ordered:
   qs=model._default_manager.all()
   if model._meta.label_lower=='erp.codesequence':
    qs.filter(organization=org).update(nextSequence=1);qs=qs.exclude(organization=org)
   if model._meta.label_lower=='hrms.policy':qs=qs.exclude(organization=org) # Required HR policy configuration.
   qs._raw_delete(qs.db) # Intentional reset: ordered FK-safe deletion bypasses posted-record edit guards.
  for label in ['token_blacklist.BlacklistedToken','token_blacklist.OutstandingToken','sessions.Session','admin.LogEntry']:
   try:model=apps.get_model(label)
   except LookupError:continue
   model.objects.all().delete()
  User.objects.exclude(pk=admin.pk).delete()
  Role.objects.exclude(organization=org).delete();Organization.objects.exclude(pk=org.pk).delete()
  warehouse=m.Location.objects.create(organization=org,name=opts['warehouse_name'],code='WH01',kind='Warehouse',status='active')
  branch=m.Location.objects.create(organization=org,name=opts['branch_name'],code='BR01',kind='Branch',status='active',warehouse=warehouse)
  warehouse.ownerBranch=branch;warehouse.save(update_fields=['ownerBranch'])
  org.defaultBranch=branch;org.defaultWarehouse=warehouse;org.singleLocationMode=True;org.save(update_fields=['defaultBranch','defaultWarehouse','singleLocationMode'])
  admin.refresh_from_db();admin.organization=org;admin.role='owner';admin.branch=branch;admin.warehouse=warehouse;admin.save(update_fields=['organization','role','branch','warehouse'])
  call_command('bootstrap_access',verbosity=0)
  from apps.pos.models import Register
  Register.objects.create(organization=org,branch=branch,name='Main POS Register')
  self.stdout.write(self.style.SUCCESS(f'Reset complete. Preserved {admin.username} and its password. 1 admin, 1 physical branch, 1 warehouse, 0 products/fragrances/customers/suppliers/purchases/sales/stock. Single-location mode enabled. Sign in again.'))
