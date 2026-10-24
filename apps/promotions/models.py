from django.db import models
from apps.erp.models import TenantModel, Product, Location, Invoice, money

class Offer(TenantModel):
    TYPES=[('BUY_X_GET_Y','Buy X Get Y'),('PERCENTAGE_DISCOUNT','Percentage discount'),('FIXED_DISCOUNT','Fixed discount')]
    name=models.CharField(max_length=160)
    code=models.CharField(max_length=50)
    description=models.TextField(blank=True)
    offer_type=models.CharField(max_length=40,choices=TYPES)
    status=models.CharField(max_length=12,choices=[('draft','Draft'),('active','Active'),('paused','Paused'),('archived','Archived')],default='draft')
    starts_at=models.DateTimeField(null=True,blank=True)
    ends_at=models.DateTimeField(null=True,blank=True)
    buy_quantity=models.PositiveIntegerField(default=1)
    get_quantity=models.PositiveIntegerField(default=1)
    discount_percentage=models.DecimalField(max_digits=6,decimal_places=2,default=0)
    discount_amount=money()
    repeatable=models.BooleanField(default=True)
    automatic=models.BooleanField(default=True)
    priority=models.IntegerField(default=0)
    products=models.ManyToManyField(Product,blank=True,related_name='offers')
    branches=models.ManyToManyField(Location,blank=True,related_name='offers')
    class Meta:
        constraints=[models.UniqueConstraint(fields=['organization','code'],name='promotion_code_org')]
    def __str__(self): return self.name

class Redemption(TenantModel):
    offer=models.ForeignKey(Offer,on_delete=models.PROTECT)
    invoice=models.ForeignKey(Invoice,on_delete=models.PROTECT,related_name='offer_redemptions')
    discount=money()
    snapshot=models.JSONField(default=dict)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['offer','invoice'],name='promotion_once_per_invoice')]
