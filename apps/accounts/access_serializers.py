"""Typed OpenAPI contracts for access endpoints; provisioning remains service-validated."""
from rest_framework import serializers
from .models import PermissionAuditLog,Permission
class UserAccessSerializer(serializers.Serializer):
 id=serializers.IntegerField(read_only=True)
 username=serializers.CharField(max_length=150)
 name=serializers.CharField(max_length=150,required=False)
 email=serializers.EmailField(required=False,allow_blank=True)
 phone=serializers.CharField(max_length=40,required=False,allow_blank=True)
 password=serializers.CharField(write_only=True,required=False)
 is_active=serializers.BooleanField(default=True)
 roles=serializers.ListField(child=serializers.IntegerField())
 branches=serializers.ListField(child=serializers.CharField(),required=False)
 employee=serializers.CharField(required=False,allow_blank=True)
 permissions=serializers.ListField(child=serializers.CharField(),read_only=True)
 scope=serializers.CharField(read_only=True)
class PermissionCatalogSerializer(serializers.ModelSerializer):
 class Meta:model=Permission;fields=['code','module','resource','action']
class RoleOptionSerializer(serializers.Serializer):
 id=serializers.IntegerField();name=serializers.CharField();scope=serializers.CharField()
class BranchOptionSerializer(serializers.Serializer):
 id=serializers.CharField();name=serializers.CharField()
class MyPermissionsSerializer(serializers.Serializer):
 permissions=serializers.ListField(child=serializers.CharField());scope=serializers.CharField();locations=serializers.ListField(child=serializers.CharField())
class AuditSerializer(serializers.ModelSerializer):
 actor__username=serializers.CharField(read_only=True)
 class Meta:model=PermissionAuditLog;fields=['id','action','target','actor__username','before','after','created_at']
