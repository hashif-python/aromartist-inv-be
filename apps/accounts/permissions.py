from rest_framework.permissions import BasePermission
ROLE_PERMISSIONS = {
 'owner':['*'],
 'warehouse_manager':['warehouse.view','warehouse.manage','inventory.view','inventory.adjust','inventory.wastage','purchases.view','purchases.grn','purchases.returns','production.view','production.add_batch','transfers.view','transfers.create','transfers.dispatch','transfers.receive'],
 'branch_manager':['branch.view','branch.manage_stock','inventory.view','sales.view','sales.pos','sales.returns','customers.manage','transfers.view','transfers.create','transfers.receive','reports.branch'],
 'production_manager':['inventory.view','inventory.wastage','production.view','production.formulation','production.add_batch','production.complete','production.wastage','transfers.view'],
 'cashier':['sales.pos','sales.view','customers.quick_add','sales.returns'],
 'accountant':['finance.view','finance.expenses','finance.receivables','finance.payables','finance.cash_bank','reports.finance','purchases.bills'],
 'staff':['inventory.view','sales.view'],
}
def has(user,*permissions):
    if not user.is_authenticated or not user.is_active:return False
    from .access import effective_permissions
    owned=effective_permissions(user)
    if user.is_superuser or '*' in owned:return True
    if any(p in owned for p in permissions):return True
    aliases={'inventory.view':['inventory.'],'production.view':['inventory.fragrance.','inventory.formulation.','inventory.product.','inventory.variant.','inventory.bottle_setup.','inventory.batch.'],'purchases.view':['purchases.'],'sales.view':['sales.'],'finance.view':['accounting.'],'warehouse.view':['administration.warehouse.'],'branch.view':['administration.branch.']}
    for p in permissions:
        if any(code.endswith('.view') and code.startswith(prefix) for prefix in aliases.get(p,[]) for code in owned):return True
    gates={'warehouse.manage':['inventory.raw_material.create','inventory.raw_material.edit','inventory.raw_material.delete','administration.warehouse.create','administration.warehouse.edit','inventory.category.create','inventory.category.edit'],'inventory.adjust':['inventory.adjustment.create'],'inventory.wastage':['inventory.wastage.create'],'production.formulation':['inventory.formulation.create','inventory.formulation.edit','inventory.fragrance.create','inventory.product.create','inventory.product.edit','inventory.variant.edit','inventory.bottle_setup.create','inventory.bottle_setup.edit'],'production.complete':['inventory.product.manufacture','inventory.batch.complete'],'production.add_batch':['inventory.batch.create'],'sales.pos':['sales.invoice.checkout'],'customers.manage':['sales.customer.create','sales.customer.edit','sales.customer.delete'],'customers.quick_add':['sales.customer.create'],'finance.expenses':['accounting.expense.create','accounting.expense.edit','accounting.expense.delete'],'finance.payables':['purchases.bill.pay'],'finance.cash_bank':['accounting.ledger.create','accounting.ledger.edit'],'transfers.create':['inventory.transfer.create'],'transfers.receive':['inventory.transfer.receive'],'transfers.dispatch':['inventory.transfer.dispatch']}
    return any(any(code in owned for code in gates.get(p,[])) for p in permissions)

class BusinessPermission(BasePermission):
    def has_permission(self,request,view):
        u=request.user
        if not u.is_authenticated or not u.is_active or not u.organization_id:return False
        from .access import RESOURCES,effective_permissions
        resource=next((code for code,cls in RESOURCES.items() if cls==type(view).__name__),None)
        action=getattr(view,'action',None)
        if resource:
            verb={'list':'view','retrieve':'view','create':'create','update':'edit','partial_update':'edit','destroy':'delete','dispatch_transfer':'dispatch','unified_update':'edit','costing':'view','pricing':'edit','unified':'create','create_unified':'create','workspace':'view','preview':'view','stock':'view','complete':'complete','approve':'approve','pay':'pay'}.get(action,action)
            exact=effective_permissions(u)
            if '*' in exact or f'{resource}.{verb}' in exact:
                from .scope_context import permission_context
                permission_context.set(f'{resource}.{verb}');return True
            # Legacy codes are still explicit configurable permissions. Derived UI aliases never grant a resource action.
            requirements=view.read_permissions if request.method in ('GET','HEAD','OPTIONS') else view.write_permissions
            if action in getattr(view,'action_permissions',{}):requirements=view.action_permissions[action]
            from .scope_context import permission_context
            granted=next((p for p in requirements if p in exact),None)
            permission_context.set(granted);return bool(granted)
        requirements=view.read_permissions if request.method in ('GET','HEAD','OPTIONS') else view.write_permissions
        if action in getattr(view,'action_permissions',{}):requirements=view.action_permissions[action]
        exact=effective_permissions(u)
        mode=getattr(view,'mode',None)
        modes={'stock':['inventory.stock.view'],'low':['inventory.stock.view'],'reports':['reports.view'],'cash-bank':['accounting.ledger.view'],'income':['accounting.ledger.view'],'finance':['accounting.ledger.view'],'receivables':['sales.invoice.view'],'payables':['purchases.bill.view'],'payments':['purchases.bill.view'] if request.method=='GET' else ['purchases.bill.pay'],'availability':['inventory.product.manufacture','inventory.batch.create'],'checkout':['sales.invoice.checkout']}
        if mode in ['dashboard','alerts']:return '*' in exact or any(p in exact for p in requirements) or any(p.endswith('.view') and p.startswith(('inventory.','sales.','accounting.','purchases.')) for p in exact)
        if mode in modes:
            from .scope_context import permission_context
            granted=next((p for p in modes[mode]+requirements if p in exact),None)
            permission_context.set(granted);return '*' in exact or bool(granted)
        return any(p in exact for p in requirements) or '*' in exact
