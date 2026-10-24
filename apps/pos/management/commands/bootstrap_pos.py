from django.core.management.base import BaseCommand
from django.db import transaction
from apps.accounts.models import Organization,Role,Permission
from apps.erp.models import Location
from apps.pos.models import Register
from apps.pos.permissions import CODES,CASHIER
class Command(BaseCommand):
    help='Create missing POS Cashier roles/registers; preserve existing role definitions and assignments.'
    @transaction.atomic
    def handle(self,*args,**options):
        for code in CODES:
            resource,action=code.rsplit('.',1)
            Permission.objects.get_or_create(code=code,defaults={'module':'pos','resource':resource,'action':action})
        for org in Organization.objects.all():
            Role.objects.get_or_create(organization=org,name='POS Cashier',defaults={'scope':'branches','permissions':list(CASHIER)})
            for branch in Location.objects.filter(organization=org,kind='Branch',status='active'):
                Register.objects.get_or_create(organization=org,branch=branch,name='Main Register')
        self.stdout.write('POS role and missing registers ready. Existing access assignments are unchanged.')
