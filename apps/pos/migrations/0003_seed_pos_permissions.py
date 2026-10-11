from django.db import migrations
CODES=['pos.access', 'pos.dashboard.view', 'pos.stock.view', 'pos.order.view', 'pos.order.edit_draft', 'pos.order.cancel', 'pos.discount.apply', 'pos.receipt.view', 'pos.receipt.share', 'pos.register.open', 'pos.register.close', 'pos.register.cash_adjust', 'pos.register.approve_discrepancy', 'pos.orders.branch', 'pos.sales_history.view', 'pos.refund.process']
def seed(apps,schema_editor):
 Permission=apps.get_model("accounts","Permission")
 for code in CODES:
  resource,action=code.rsplit(".",1)
  Permission.objects.get_or_create(code=code,defaults={"module":"pos","resource":resource,"action":action})
class Migration(migrations.Migration):
 dependencies=[("pos","0002_refund_fingerprint_refund_requestkey_shift_closedby_and_more")]
 operations=[migrations.RunPython(seed,migrations.RunPython.noop)]
