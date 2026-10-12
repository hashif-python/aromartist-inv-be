from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers
from django.contrib.auth import get_user_model
from .permissions import ROLE_PERMISSIONS
class ProfileSerializer(serializers.ModelSerializer):
    def to_representation(self,instance):
        data=super().to_representation(instance)
        employee=instance.employees.filter(organization_id=instance.organization_id).first()
        if employee:data.update(name=employee.name,email=employee.email,phone=employee.phone)
        return data
    name=serializers.CharField(source='first_name',required=False)
    permissions=serializers.SerializerMethodField()
    organization=serializers.CharField(source='organization.name',read_only=True,default='')
    branch=serializers.CharField(source='branch.name',read_only=True,default='')
    warehouse=serializers.CharField(source='warehouse.name',read_only=True,default='')
    branchId=serializers.CharField(source='branch_id',read_only=True,allow_null=True)
    warehouseId=serializers.CharField(source='warehouse_id',read_only=True,allow_null=True)
    @extend_schema_field(serializers.JSONField())
    def get_permissions(self,o):
        from .access import effective_permissions
        return effective_permissions(o)
    storeSetup=serializers.SerializerMethodField()
    @extend_schema_field(serializers.JSONField())
    def get_storeSetup(self,o):
        if not o.organization_id:return {'singleLocationMode':False}
        org=o.organization
        return dict(singleLocationMode=org.singleLocationMode,branchId=org.defaultBranch_id,branchName=org.defaultBranch.name if org.defaultBranch_id else '',warehouseId=org.defaultWarehouse_id,warehouseName=org.defaultWarehouse.name if org.defaultWarehouse_id else '')
    accessScope=serializers.SerializerMethodField()
    def get_accessScope(self,o):
        from .access import scope
        return scope(o)
    class Meta:
        model=get_user_model()
        fields=['id','username','name','email','phone','bio','role','permissions','accessScope','organization','branch','warehouse','branchId','warehouseId','storeSetup']
        read_only_fields=['id','username','role']
class LoginSerializer(serializers.Serializer):
    username=serializers.CharField()
    password=serializers.CharField(write_only=True)
    role=serializers.CharField(required=False)
class PasswordSerializer(serializers.Serializer):
    currentPassword=serializers.CharField(write_only=True)
    newPassword=serializers.CharField(write_only=True)
class ResetSerializer(serializers.Serializer):
    email=serializers.EmailField()
class ResetConfirmSerializer(serializers.Serializer):
    uid=serializers.CharField()
    token=serializers.CharField()
    newPassword=serializers.CharField(write_only=True)

class LogoutSerializer(serializers.Serializer):
    refresh=serializers.CharField(required=False)

class LoginResponseSerializer(serializers.Serializer):
    access=serializers.CharField()
    user=ProfileSerializer()
class AccessResponseSerializer(serializers.Serializer):
    access=serializers.CharField()
