from django.contrib.auth.models import AbstractUser
from django.db import models

class Organization(models.Model):
    name=models.CharField(max_length=160)
    created_at=models.DateTimeField(auto_now_add=True)
    def __str__(self): return self.name

class User(AbstractUser):
    ROLES=[(r,r.replace('_',' ').title()) for r in ['owner','warehouse_manager','branch_manager','production_manager','cashier','accountant','staff']]
    organization=models.ForeignKey(Organization,on_delete=models.PROTECT,null=True,blank=True)
    role=models.CharField(max_length=30,choices=ROLES,default='staff')
    branch=models.ForeignKey('erp.Location',on_delete=models.PROTECT,null=True,blank=True,related_name='branch_users',limit_choices_to={'kind':'Branch'})
    warehouse=models.ForeignKey('erp.Location',on_delete=models.PROTECT,null=True,blank=True,related_name='warehouse_users',limit_choices_to={'kind':'Warehouse'})
    phone=models.CharField(max_length=40,blank=True)
    bio=models.TextField(blank=True)
    def clean(self):
        super().clean()
        from django.core.exceptions import ValidationError
        for name,kind in [('branch','Branch'),('warehouse','Warehouse')]:
            obj=getattr(self,name)
            if obj and (obj.organization_id!=self.organization_id or obj.kind!=kind):
                raise ValidationError({name:'Select a location of this type within the user organization.'})

from .access_models import Role,UserRoleAssignment,UserBranchAssignment,PermissionAuditLog,Permission
