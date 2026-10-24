from django.contrib import admin
from .models import Register,Shift,CashMovement,Sale,Draft
@admin.register(Register)
class RegisterAdmin(admin.ModelAdmin):
    list_display=['name','branch','organization','active','discrepancyLimit']
@admin.register(Shift,CashMovement,Sale,Draft)
class HistoryAdmin(admin.ModelAdmin):
    def has_add_permission(self,request):return False
    def has_change_permission(self,request,obj=None):return False
    def has_delete_permission(self,request,obj=None):return False
