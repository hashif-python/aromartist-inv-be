from django.db import models
from .models import Organization, User
class Role(models.Model):
 organization=models.ForeignKey(Organization,on_delete=models.CASCADE)
 name=models.CharField(max_length=100)
 permissions=models.JSONField(default=list)
 scope=models.CharField(max_length=20,choices=[(v,v) for v in ['own','team','branches','organization']],default='own')
 class Meta: constraints=[models.UniqueConstraint(fields=['organization','name'],name='role_org_name')]
class UserRoleAssignment(models.Model):
 user=models.ForeignKey(User,on_delete=models.CASCADE,related_name='roleAssignments')
 role=models.ForeignKey(Role,on_delete=models.PROTECT)
 class Meta: constraints=[models.UniqueConstraint(fields=['user','role'],name='user_role_unique')]
class UserBranchAssignment(models.Model):
 user=models.ForeignKey(User,on_delete=models.CASCADE,related_name='branchAssignments')
 branch=models.ForeignKey('erp.Location',on_delete=models.PROTECT)
 class Meta: constraints=[models.UniqueConstraint(fields=['user','branch'],name='user_branch_unique')]
class PermissionAuditLog(models.Model):
 organization=models.ForeignKey(Organization,on_delete=models.PROTECT)
 actor=models.ForeignKey(User,on_delete=models.SET_NULL,null=True)
 action=models.CharField(max_length=100)
 target=models.CharField(max_length=100)
 before=models.JSONField(default=dict)
 after=models.JSONField(default=dict)
 created_at=models.DateTimeField(auto_now_add=True)
class Permission(models.Model):
 code=models.CharField(max_length=140,unique=True)
 module=models.CharField(max_length=60)
 resource=models.CharField(max_length=100)
 action=models.CharField(max_length=40)
 class Meta:ordering=['code']
