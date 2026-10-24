from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Organization
@admin.register(User)
class ERPUserAdmin(UserAdmin):
    fieldsets=UserAdmin.fieldsets+(('ERP assignment',{'fields':['organization','role','branch','warehouse','phone','bio']}),)
    list_display=['username','email','organization','role','branch','warehouse','is_active']
    list_filter=UserAdmin.list_filter+('organization','role')
@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display=['name','created_at'];search_fields=['name'];readonly_fields=['created_at']

from .models import Role,Permission,UserRoleAssignment,UserBranchAssignment,PermissionAuditLog
admin.site.register([Role,Permission,UserRoleAssignment,UserBranchAssignment])
@admin.register(PermissionAuditLog)
class AuditAdmin(admin.ModelAdmin):
 readonly_fields=['organization','actor','action','target','before','after','created_at']
 def has_add_permission(self,request):return False
 def has_change_permission(self,request,obj=None):return False
 def has_delete_permission(self,request,obj=None):return False
