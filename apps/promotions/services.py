"""Server-authoritative first-phase promotion engine. No client-provided totals are trusted."""
from decimal import Decimal,ROUND_HALF_UP
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from .models import Offer,Redemption

CENT=Decimal('.01')
def rounded(n): return n.quantize(CENT,rounding=ROUND_HALF_UP)

def available(organization,branch):
    now=timezone.now()
    return (Offer.objects.filter(organization=organization,status='active',automatic=True)
      .filter(models.Q(starts_at__isnull=True)|models.Q(starts_at__lte=now))
      .filter(models.Q(ends_at__isnull=True)|models.Q(ends_at__gte=now))
      .prefetch_related('products','branches').order_by('-priority','id'))

from django.db import models

def calculate(organization,branch,lines):
    """lines: [{productId, qty, rate}]. Uses best single non-stacked offer.
    Reward selection is same-product only in this safe first phase.
    """
    normalized=[]
    for line in lines:
        qty=int(line['qty']); rate=Decimal(str(line['rate']))
        if qty<=0 or rate<0:raise ValidationError('Invalid offer quote line.')
        normalized.append({'productId':str(line['productId']),'qty':qty,'rate':rate})
    best=None
    for offer in available(organization,branch):
        branch_ids={str(x.pk) for x in offer.branches.all()}
        if branch_ids and str(branch.pk) not in branch_ids:continue
        ids={str(x.pk) for x in offer.products.all()}
        eligible=[x for x in normalized if x['productId'] in ids]
        if not eligible:continue
        discount=Decimal(0)
        if offer.offer_type=='BUY_X_GET_Y':
            if not offer.buy_quantity or not offer.get_quantity:continue
            for line in eligible:
                group=offer.buy_quantity+offer.get_quantity
                free=(line['qty']//group)*offer.get_quantity
                if not offer.repeatable:free=min(free,offer.get_quantity)
                discount+=line['rate']*free
        elif offer.offer_type=='PERCENTAGE_DISCOUNT':
            if offer.discount_percentage<0 or offer.discount_percentage>100:continue
            discount=sum((x['rate']*x['qty'] for x in eligible),Decimal(0))*offer.discount_percentage/100
        elif offer.offer_type=='FIXED_DISCOUNT':
            discount=sum((min(x['rate'],offer.discount_amount)*x['qty'] for x in eligible),Decimal(0))
        discount=min(rounded(discount),sum((x['rate']*x['qty'] for x in eligible),Decimal(0)))
        if discount>0 and (best is None or discount>best['discount']):
            best={'offer':offer,'discount':discount,'eligibleIds':ids}
    return best

def apply_to_invoice(invoice):
    lines=list(invoice.lines.select_related('product','variant').order_by('pk'))
    entries=[{'productId':line.product_id or line.variant.productId_id,'qty':line.qty,'rate':line.rate} for line in lines]
    result=calculate(invoice.organization,invoice.branch,entries)
    if not result:return None
    # Preserve the invoice's existing per-line discounts, and allocate promotion
    # only against the remaining payable amounts.
    eligible=[l for l in lines if str(l.product_id or l.variant.productId_id) in result['eligibleIds']]
    base=sum((l.total for l in eligible),Decimal(0))
    amount=min(result['discount'],base)
    if amount<=0:return None
    remaining=amount
    for i,line in enumerate(eligible):
        portion=remaining if i==len(eligible)-1 else min(line.total,rounded(amount*line.total/base))
        portion=min(portion,line.total)
        line.discount+=portion
        line.total-=portion
        line.save(update_fields=['discount','total'])
        remaining-=portion
    applied=amount-remaining
    invoice.discount+=applied
    invoice.total-=applied
    Redemption.objects.create(organization=invoice.organization,offer=result['offer'],invoice=invoice,discount=applied,snapshot={'name':result['offer'].name,'code':result['offer'].code,'type':result['offer'].offer_type})
    return applied
