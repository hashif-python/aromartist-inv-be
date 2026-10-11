from django.db import models
from django.db.models import Q
from apps.erp.models import TenantModel,relation,money

class Register(TenantModel):
    branch=relation('erp.Location')
    name=models.CharField(max_length=100)
    active=models.BooleanField(default=True)
    discrepancyLimit=money(default=50)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['branch','name'],name='pos_register_name')]

class Shift(TenantModel):
    organization=relation('accounts.Organization',related_name='pos_shifts')
    register=relation(Register)
    cashier=relation('accounts.User')
    opened_at=models.DateTimeField(auto_now_add=True)
    closed_at=models.DateTimeField(null=True,blank=True)
    closingRequested=models.BooleanField(default=False)
    closedBy=relation('accounts.User',null=True,blank=True,related_name='pos_closed_shifts')
    opening=money()
    counted=money(default=0)
    expected=money(default=0)
    difference=models.DecimalField(max_digits=18,decimal_places=2,default=0)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['register'],condition=Q(closed_at__isnull=True),name='pos_one_register_shift'),models.UniqueConstraint(fields=['cashier'],condition=Q(closed_at__isnull=True),name='pos_one_cashier_shift')]

class CashMovement(TenantModel):
    shift=relation(Shift,related_name='movements')
    cashier=relation('accounts.User')
    amount=money()
    kind=models.CharField(max_length=3,choices=[('In','In'),('Out','Out')])
    reason=models.CharField(max_length=250)
    ledger=relation('erp.LedgerEntry')

class Sale(TenantModel):
    invoice=models.OneToOneField('erp.Invoice',on_delete=models.PROTECT,related_name='pos_sale')
    shift=relation(Shift,related_name='sales')
    tendered=money()

class Draft(TenantModel):
    cashier=relation('accounts.User')
    branch=relation('erp.Location')
    label=models.CharField(max_length=100,default='Held sale')
    payload=models.JSONField(default=dict)
    revision=models.PositiveIntegerField(default=1)
    status=models.CharField(max_length=10,default='Draft')
    invoice=relation('erp.Invoice',null=True,blank=True)

class Refund(TenantModel):
    requestKey=models.CharField(max_length=64,blank=True)
    fingerprint=models.CharField(max_length=64,blank=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['organization','requestKey'],condition=~Q(requestKey=''),name='pos_refund_request')]

    returned=models.OneToOneField('erp.SalesReturn',on_delete=models.PROTECT,related_name='pos_refund')
    shift=relation(Shift,related_name='refunds')
    cashier=relation('accounts.User')
