from django.contrib import admin
from .models import Offer,Redemption
@admin.register(Offer)
class OfferAdmin(admin.ModelAdmin):
    list_display=('name','code','organization','offer_type','status','starts_at','ends_at')
    list_filter=('status','offer_type')
    search_fields=('name','code')
    filter_horizontal=('products','branches')
@admin.register(Redemption)
class RedemptionAdmin(admin.ModelAdmin):
    list_display=('offer','invoice','discount','created_at')
    readonly_fields=('offer','invoice','discount','snapshot','organization')
    def has_add_permission(self,request):return False
