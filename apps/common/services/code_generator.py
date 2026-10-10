"""Organization-scoped identifiers. PostgreSQL transaction locks serialize allocation.
API serializers ignore supplied identifiers; trusted imports may preserve existing codes.
A failed transaction issues no record and rolls allocation back with that record.
"""
import re
from datetime import date
from django.db import transaction
from django.db.models import F
from rest_framework.exceptions import ValidationError

# Only real identifier fields are registered. External references are excluded.
FIELDS={
 ('erp','supplier'):('code','SUP',False),
 ('erp','material'):('code','RM',False),
 ('erp','fragrance'):('code','FRG',False),
 ('erp','concentration'):('code','CON',False),
 ('erp','formula'):('code','FRM',False),
 ('erp','product'):('code','PRD',False),
 ('erp','variant'):('sku','SKU',False),
 ('erp','batch'):('batchNo','PB',True),
 ('erp','transfer'):('transferNo','TRF',True),
 ('erp','purchaseorder'):('poNumber','PO',True),
 ('erp','receipt'):('grnNumber','GRN',True),
 ('erp','bill'):('billNumber','BILL',True),
 ('erp','purchasereturn'):('returnNumber','PR',True),
 ('erp','invoice'):('invoiceNumber','INV',True),
 ('erp','salesreturn'):('returnRef','SR',True),
 ('erp','expense'):('reference','EXP',True),
 ('hrms','employee'):('employeeCode','EMP',False),
 ('hrms','designation'):('code','DSG',False),
}

def config_for(instance):
 key=(instance._meta.app_label,instance._meta.model_name)
 if key==('erp','location'):return ('code','BR' if instance.kind=='Branch' else 'WH',False)
 if key==('erp','ledgerentry') and instance.source=='manual':return ('reference','INC' if instance.type=='Inflow' else 'OUT',True)
 return FIELDS.get(key)

def identifier_fields(model):
 key=(model._meta.app_label,model._meta.model_name)
 if key in [('erp','location'),('erp','ledgerentry')]:return ['code' if key[1]=='location' else 'reference']
 return [FIELDS[key][0]] if key in FIELDS else []

@transaction.atomic
def allocate(organization,document_type,prefix,yearly=False,model=None,field=None,day=None):
 from apps.accounts.models import Organization
 from apps.erp.models import CodeSequence
 # This also locks the first allocation, before the sequence row exists.
 Organization.objects.select_for_update().get(pk=organization.pk)
 period=(day or date.today()).year if yearly else 0
 sequence,_=CodeSequence.objects.get_or_create(organization=organization,documentType=document_type,period=period,defaults={'prefix':prefix})
 sequence=CodeSequence.objects.select_for_update().get(pk=sequence.pk)
 if not sequence.active:raise ValidationError('This identifier sequence is inactive; ask an administrator.')
 if not re.fullmatch(r'[A-Z][A-Z0-9_-]{0,19}',sequence.prefix) or not 1<=sequence.padding<=12:raise ValidationError('Invalid sequence prefix or padding configuration.')
 while True:
  value=sequence.nextSequence
  CodeSequence.objects.filter(pk=sequence.pk).update(nextSequence=F('nextSequence')+1)
  sequence.refresh_from_db(fields=['nextSequence'])
  candidate=f'{sequence.prefix}-{period}-' if yearly else f'{sequence.prefix}-'
  candidate+=str(value).zfill(sequence.padding)
  if model is None or not model.objects.filter(organization=organization,**{field:candidate}).exists():return candidate

def generate_for(instance):
 cfg=config_for(instance)
 if not cfg:return
 field,prefix,yearly=cfg
 if getattr(instance,field,''):return
 day=next((getattr(instance,k,None) for k in ['date','orderDate','receiveDate'] if isinstance(getattr(instance,k,None),date)),None)
 setattr(instance,field,allocate(instance.organization,f'{instance._meta.label_lower}.{prefix}',prefix,yearly,instance.__class__,field,day))
