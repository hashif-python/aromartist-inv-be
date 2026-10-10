from django.db.models import Q
from .models import Role,UserRoleAssignment,UserBranchAssignment
# Resource actions are distinct from legacy workflow gates.
RESOURCES={
 'inventory.raw_material':'MaterialViewSet','inventory.category':'MaterialCategoryViewSet','inventory.fragrance':'FragranceViewSet','inventory.formulation':'FormulaViewSet','inventory.product':'ProductViewSet','inventory.variant':'VariantViewSet','inventory.bottle_setup':'BottleSizeViewSet','inventory.concentration':'ConcentrationViewSet','inventory.movement':'MovementViewSet','inventory.adjustment':'AdjustmentViewSet','inventory.wastage':'WastageViewSet','inventory.transfer':'TransferViewSet','administration.warehouse':'LocationViewSet','administration.branch':'BranchViewSet','purchases.supplier':'SupplierViewSet','purchases.order':'PurchaseOrderViewSet','purchases.grn':'ReceiptViewSet','purchases.bill':'BillViewSet','purchases.return':'PurchaseReturnViewSet','sales.customer':'CustomerViewSet','sales.invoice':'InvoiceViewSet','sales.return':'SalesReturnViewSet','accounting.expense':'ExpenseViewSet','accounting.ledger':'LedgerViewSet','inventory.batch':'BatchViewSet'}
HR_RESOURCES=['dashboard','employee','department','designation','attendance','leave_type','leave_balance','leave','salary','salary_revision','payroll_period','payroll','advance','document','shift','shift_assignment','holiday','policy']
ACTIONS=['manufacture','complete','receive','dispatch','checkout','reverse','view','create','edit','delete','approve','reject','cancel','calculate','pay','disburse','export','download','link_login','check_in','check_out']
def catalog():
 from .permissions import ROLE_PERMISSIONS
 legacy=sorted({p for rows in ROLE_PERMISSIONS.values() for p in rows if p!='*'})
 return legacy+[f'{resource}.{a}' for resource in RESOURCES for a in ACTIONS]+[f'hrms.{resource}.{a}' for resource in HR_RESOURCES for a in ACTIONS]+['inventory.stock.view','reports.view','access.users.manage','access.roles.manage','access.audit.view','hrms.self_attendance']
def assigned_permissions(user):
 assignments=list(user.roleAssignments.select_related('role'))
 if assignments:return sorted({p for a in assignments for p in a.role.permissions})
 from .permissions import ROLE_PERMISSIONS
 return ROLE_PERMISSIONS.get(user.role,[]) # compatibility for newly-created legacy admin users

def effective_permissions(user):
 return ['*'] if user.is_superuser else assigned_permissions(user)
def scope(user):
 if user.is_superuser or '*' in assigned_permissions(user):return 'organization'
 from .scope_context import permission_context
 permission=permission_context.get()
 roles=[a.role for a in user.roleAssignments.select_related('role')]
 if permission:roles=[r for r in roles if permission in r.permissions or '*' in r.permissions]
 scopes=[r.scope for r in roles]
 if permission and not roles and user.roleAssignments.exists():return 'own'
 if scopes:return next((s for s in ['organization','branches','team','own'] if s in scopes),'own')
 return 'organization' if user.role in ['owner','accountant'] else 'branches'
def location_ids(user):
 ids=set(user.branchAssignments.values_list('branch_id',flat=True));ids.update(i for i in [user.branch_id,user.warehouse_id] if i)
 from apps.erp.models import Location
 ids.update(Location.objects.filter(pk__in=ids,kind='Branch').exclude(warehouse=None).values_list('warehouse_id',flat=True))
 return ids
def employee_ids(user):
 from apps.hrms.models import Employee
 qs=Employee.objects.filter(organization_id=user.organization_id)
 s=scope(user)
 if s=='organization':return qs.values_list('pk',flat=True)
 if s=='branches':return qs.filter(branch_id__in=location_ids(user)).values_list('pk',flat=True)
 own=set(qs.filter(user=user).values_list('pk',flat=True));ids=set(own)
 if s=='team':
  while True:
   next_ids=set(qs.filter(manager_id__in=ids).values_list('pk',flat=True))-ids
   if not next_ids:break
   ids.update(next_ids)
 return ids

def scoped_erp(qs,user):
 if scope(user)=='organization':return qs
 ids=location_ids(user);fields={f.name for f in qs.model._meta.fields};name=qs.model.__name__
 if name=='Location':return qs.filter(pk__in=ids)
 if name=='Stock':return qs.filter(location_id__in=ids)
 lookups={'Receipt':'order__warehouse_id','Bill':'order__warehouse_id','SupplierPayment':'bill__order__warehouse_id','SalesReturn':'line__invoice__branch_id','Movement':'stock__location_id','Wastage':'stock__location_id','InvoiceLine':'invoice__branch_id','PurchaseLine':'order__warehouse_id'}
 if name in lookups:return qs.filter(**{lookups[name]+'__in':ids})
 if name=='Transfer':return qs.filter(Q(source_id__in=ids)|Q(destination_id__in=ids))
 if 'branch' in fields:return qs.filter(branch_id__in=ids)
 if 'warehouse' in fields:return qs.filter(warehouse_id__in=ids)
 if name=='Expense':
  from apps.erp.models import Location
  return qs.filter(location__in=Location.objects.filter(pk__in=ids).values_list('name',flat=True))
 if name=='LedgerEntry':return qs.none() # branch-scoped cash ledgers require an explicit organization-scoped finance role
 return qs # tenant-wide shared catalogs have no physical balance of their own
