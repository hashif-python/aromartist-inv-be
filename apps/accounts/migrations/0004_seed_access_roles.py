from django.db import migrations
LEGACY={
 'owner':('Organization Admin',['*'],'organization'),
 'warehouse_manager':('Inventory Manager',['warehouse.view','warehouse.manage','inventory.view','inventory.adjust','inventory.wastage','purchases.view','purchases.grn','purchases.returns','production.view','production.add_batch','transfers.view','transfers.create','transfers.dispatch','transfers.receive'],'branches'),
 'branch_manager':('Branch Manager',['branch.view','branch.manage_stock','inventory.view','sales.view','sales.pos','sales.returns','customers.manage','transfers.view','transfers.create','transfers.receive','reports.branch'],'branches'),
 'production_manager':('Production Staff',['inventory.view','inventory.wastage','production.view','production.formulation','production.add_batch','production.complete','production.wastage','transfers.view'],'branches'),
 'cashier':('Cashier',['sales.pos','sales.view','customers.quick_add','sales.returns'],'branches'),
 'accountant':('Accountant',['finance.view','finance.expenses','finance.receivables','finance.payables','finance.cash_bank','reports.finance','purchases.bills','hrms.payroll.view','hrms.payroll.pay','hrms.payroll.download','hrms.advance.view','hrms.advance.disburse'],'organization'),
 'staff':('Legacy Staff',['inventory.view','sales.view'],'branches')}
HR=['dashboard','employee','department','designation','attendance','leave_type','leave_balance','leave','salary','salary_revision','payroll_period','payroll','advance','document','shift','shift_assignment','holiday','policy']
ACT=['view','create','edit','delete','approve','reject','cancel','calculate','pay','disburse','download','export','check_in','check_out','link_login']
EMPLOYEE=['hrms.dashboard.view','hrms.employee.view','hrms.attendance.view','hrms.self_attendance','hrms.leave.view','hrms.leave.create','hrms.leave.cancel','hrms.leave_type.view','hrms.leave_balance.view','hrms.payroll.view','hrms.payroll.download','hrms.document.view','hrms.document.download','hrms.document.create','hrms.advance.view','hrms.advance.create']
EXTRA={
 'HR Manager':([f'hrms.{resource}.{a}' for resource in HR for a in ACT]+['administration.branch.view','administration.warehouse.view','hrms.self_attendance'],'organization'),
 'HR Executive':([f'hrms.{resource}.{a}' for resource in ['dashboard','employee','department','designation','attendance','leave_type','leave_balance','leave','document','shift','shift_assignment','holiday'] for a in ['view','create','edit','download']]+['administration.branch.view'],'branches'),
 'Employee':(EMPLOYEE,'own'),
 'Sales Executive':(['inventory.product.view','inventory.variant.view','sales.invoice.view','sales.invoice.create','sales.invoice.checkout','sales.customer.view','sales.customer.create','sales.customer.edit','inventory.stock.view'],'branches'),
 'Purchasing Officer':([f'purchases.{resource}.{a}' for resource in ['supplier','order','grn','return'] for a in ['view','create','edit']]+['inventory.raw_material.view','administration.warehouse.view'],'branches')}
def seed(apps,schema_editor):
 Org=apps.get_model('accounts','Organization');User=apps.get_model('accounts','User');Role=apps.get_model('accounts','Role');Assignment=apps.get_model('accounts','UserRoleAssignment');Branches=apps.get_model('accounts','UserBranchAssignment')
 for org in Org.objects.all():
  roles={}
  for legacy,(name,permissions,data_scope) in LEGACY.items():
   role,_=Role.objects.get_or_create(organization=org,name=name,defaults={'permissions':permissions,'scope':data_scope});roles[legacy]=role
  for name,(permissions,data_scope) in EXTRA.items():Role.objects.get_or_create(organization=org,name=name,defaults={'permissions':permissions,'scope':data_scope})
  for user in User.objects.filter(organization=org):
   if not Assignment.objects.filter(user=user).exists():Assignment.objects.get_or_create(user=user,role=roles.get(user.role,roles['staff']))
   if user.branch_id:Branches.objects.get_or_create(user=user,branch_id=user.branch_id)
class Migration(migrations.Migration):
 dependencies=[('accounts','0003_permissionauditlog_role_userbranchassignment_and_more')]
 operations=[migrations.RunPython(seed,migrations.RunPython.noop)]
