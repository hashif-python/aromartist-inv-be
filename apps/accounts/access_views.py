from django.db import transaction
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import viewsets,serializers
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied,ValidationError
from rest_framework.permissions import BasePermission
from apps.erp.models import Location
from .models import Role,UserRoleAssignment,UserBranchAssignment,PermissionAuditLog,Permission
from .access import catalog,effective_permissions,scope,location_ids
from .permissions import has
from .access_serializers import *
User=get_user_model()
def audit(request,action,target,before,after):PermissionAuditLog.objects.create(organization=request.user.organization,actor=request.user,action=action,target=str(target),before=before,after=after)
def grantable(actor,role):
 owned=effective_permissions(actor)
 if '*' not in owned and any(p not in owned for p in role.permissions):raise PermissionDenied('You cannot grant permissions you do not possess.')
 levels=['own','team','branches','organization']
 if levels.index(role.scope)>levels.index(scope(actor)):raise PermissionDenied('You cannot grant a broader data scope.')
def check_branches(actor,ids):
 qs=Location.objects.filter(organization=actor.organization,kind='Branch',pk__in=ids)
 if len(set(ids))!=qs.count():raise ValidationError('Choose branches in your organization.')
 if scope(actor)!='organization' and not set(ids).issubset(location_ids(actor)):raise PermissionDenied('Branch assignment is outside your scope.')
 return qs
@transaction.atomic
def _provision_user(request,data,employee=None,existing=None):
 actor=request.user
 from .models import Organization
 Organization.objects.select_for_update().get(pk=actor.organization_id)
 if employee:
  from apps.hrms.models import Employee
  from .access import employee_ids
  employee=Employee.objects.select_for_update().filter(pk=employee.pk,pk__in=employee_ids(actor)).first()
  if not employee:raise PermissionDenied('Employee is outside your authorized scope.')
  if employee.user_id and (not existing or employee.user_id!=existing.pk):raise ValidationError('Employee already has a linked login.')
  if existing and Employee.objects.filter(user=existing).exclude(pk=employee.pk).exists():raise ValidationError('User already links to another employee; relinking is not permitted.')
 elif existing:
  from apps.hrms.models import Employee
  employee=Employee.objects.select_for_update().filter(user=existing).first()
 if employee:
  data={**data,'name':employee.name,'email':employee.email,'phone':employee.phone}
  if not data.get('branches'):data['branches']=[employee.branch_id]
 if not has(actor,'access.users.manage'):raise PermissionDenied('User management access required.')
 role_ids=data.get('roles',[])
 if not isinstance(role_ids,list) or not role_ids:raise ValidationError('Assign at least one role.')
 roles=list(Role.objects.filter(organization=actor.organization,pk__in=role_ids))
 if len(roles)!=len(set(role_ids)):raise ValidationError('Choose roles in your organization.')
 for role in roles:grantable(actor,role)
 branches=list(check_branches(actor,data.get('branches',[])))
 if any(role.scope=='branches' for role in roles) and not branches:raise ValidationError('Assign branches for branch-scoped access.')
 if employee and employee.organization_id!=actor.organization_id:raise ValidationError('Employee is outside your organization.')
 if existing and existing.is_superuser:raise PermissionDenied('Platform administrators are managed in Django admin.')
 if existing and existing.pk==actor.pk:raise PermissionDenied('You cannot change your own roles or activation through this interface.')
 if existing and scope(actor)!='organization':
  assigned=set(existing.branchAssignments.values_list('branch_id',flat=True))
  if not assigned or not assigned.issubset(location_ids(actor)):raise PermissionDenied('User is outside your branch scope.')
 if existing:
  for old in existing.roleAssignments.select_related('role'):grantable(actor,old.role)
  existing=User.objects.select_for_update().get(pk=existing.pk)
  before={'roles':list(existing.roleAssignments.values_list('role_id',flat=True)),'branches':list(existing.branchAssignments.values_list('branch_id',flat=True)),'is_active':existing.is_active}
  if has(existing,'*') and (not data.get('is_active',existing.is_active) or not any('*' in role.permissions for role in roles)):
   admins=UserRoleAssignment.objects.filter(user__organization=actor.organization,user__is_active=True).exclude(user=existing)
   if not any('*' in a.role.permissions for a in admins.select_related('role')) and not User.objects.filter(organization=actor.organization,is_superuser=True,is_active=True).exclude(pk=existing.pk).exists():raise ValidationError('Keep at least one active organization administrator.')
  user=existing
 else:
  before={};username=str(data.get('username','')).strip()
  if not username or User.objects.filter(username=username).exists():raise ValidationError('Choose a unique username.')
  if employee and employee.user_id:raise ValidationError('Employee already has a linked login.')
  user=User(username=username,organization=actor.organization,role='staff')
 password=data.get('password')
 if not existing and not password:raise ValidationError('A password is required.')
 if password:
  try:validate_password(password,user)
  except DjangoValidationError as error:raise ValidationError({'password':error.messages})
  user.set_password(password)
 if 'is_active' in data and type(data['is_active'])!=bool:raise ValidationError('Activation must be true or false.')
 for key,limit in [('username',150),('name',150),('phone',40),('email',254)]:
  if key in data and (not isinstance(data[key],str) or len(data[key])>limit):raise ValidationError({key:f'Use text up to {limit} characters.'})
 if data.get('email'):serializers.EmailField().run_validation(data['email'])
 for key in ['email','phone','is_active']:
  if key in data:setattr(user,key,data[key])
 user.first_name=str(data.get('name',employee.name if employee else user.first_name));user.branch=branches[0] if branches else None;user.warehouse=user.branch.warehouse if user.branch else None
 user.save();user.roleAssignments.all().delete();user.branchAssignments.all().delete()
 for role in roles:UserRoleAssignment.objects.create(user=user,role=role)
 for branch in branches:UserBranchAssignment.objects.create(user=user,branch=branch)
 if employee:employee.user=user;employee.save(update_fields=['user'])
 audit(request,'user.updated' if existing else 'user.created',user.pk,before,{'roles':[r.pk for r in roles],'branches':[b.pk for b in branches],'is_active':user.is_active})
 return user
@transaction.atomic
def provision_user(request,data,employee=None,existing=None):
 from .scope_context import permission_context
 token=permission_context.set('access.users.manage')
 try:return _provision_user(request,data,employee,existing)
 finally:permission_context.reset(token)
class AccessPermission(BasePermission):
 def has_permission(self,request,view):
  from .scope_context import permission_context
  permission_context.set(view.required_permission)
  return request.user.is_authenticated and request.user.organization_id and has(request.user,view.required_permission)
class RoleSerializer(serializers.ModelSerializer):
 class Meta:model=Role;exclude=['organization']
 def validate(self,attrs):
  actor=self.context['request'].user;permissions=attrs.get('permissions',getattr(self.instance,'permissions',[]));data_scope=attrs.get('scope',getattr(self.instance,'scope','own'))
  if not isinstance(permissions,list) or any(type(p)!=str for p in permissions) or any(p not in catalog()+['*'] for p in permissions):raise serializers.ValidationError('Choose permission codes from the catalog.')
  role=Role(permissions=permissions,scope=data_scope);grantable(actor,role)
  if self.instance:grantable(actor,self.instance)
  return attrs
class RoleViewSet(viewsets.ModelViewSet):
 permission_classes=[AccessPermission];required_permission='access.roles.manage';serializer_class=RoleSerializer
 def get_queryset(self):
  if getattr(self,'swagger_fake_view',False):return Role.objects.none()
  return Role.objects.filter(organization=self.request.user.organization).order_by('name')
 @transaction.atomic
 def perform_create(self,serializer):
  role=serializer.save(organization=self.request.user.organization);audit(self.request,'role.created',role.pk,{},serializer.data)
 @transaction.atomic
 def perform_update(self,serializer):
  role=serializer.instance
  if role.userroleassignment_set.filter(user=self.request.user).exists():raise PermissionDenied('You cannot edit a role assigned to your own account.')
  before=RoleSerializer(role).data;role=serializer.save();audit(self.request,'role.updated',role.pk,before,serializer.data)
 @transaction.atomic
 def perform_destroy(self,instance):
  grantable(self.request.user,instance)
  if instance.userroleassignment_set.exists():raise ValidationError('Assigned roles cannot be deleted.')
  audit(self.request,'role.deleted',instance.pk,RoleSerializer(instance).data,{});instance.delete()
class UserViewSet(viewsets.ViewSet):
 serializer_class=UserAccessSerializer
 permission_classes=[AccessPermission];required_permission='access.users.manage'
 def qs(self):
  qs=User.objects.filter(organization=self.request.user.organization,is_superuser=False)
  if scope(self.request.user)!='organization':qs=qs.filter(branchAssignments__branch_id__in=location_ids(self.request.user)).distinct()
  return qs
 def data(self,user):
  employee=user.employees.first()
  return {'employee':employee.pk if employee else None,'employeeName':employee.name if employee else '','id':user.pk,'username':user.username,'name':employee.name if employee else user.first_name,'email':employee.email if employee else user.email,'phone':employee.phone if employee else user.phone,'is_active':user.is_active,'roles':list(user.roleAssignments.values_list('role_id',flat=True)),'branches':list(user.branchAssignments.values_list('branch_id',flat=True)),'permissions':effective_permissions(user),'scope':scope(user)}
 def list(self,request):return Response([self.data(u) for u in self.qs()])
 def retrieve(self,request,pk=None):
  from django.shortcuts import get_object_or_404
  return Response(self.data(get_object_or_404(self.qs(),pk=pk)))
 def create(self,request):
  employee=None
  if request.data.get('employee'):
   from apps.hrms.models import Employee
   from .access import employee_ids
   from django.shortcuts import get_object_or_404
   employee=get_object_or_404(Employee,pk=request.data['employee'],pk__in=employee_ids(request.user))
  return Response(self.data(provision_user(request,request.data,employee)),status=201)
 def partial_update(self,request,pk=None):
  from django.shortcuts import get_object_or_404
  user=get_object_or_404(self.qs(),pk=pk);data={**self.data(user),**request.data};employee=None
  if request.data.get('employee'):
   from apps.hrms.models import Employee
   from .access import employee_ids
   employee=get_object_or_404(Employee,pk=request.data['employee'],pk__in=employee_ids(request.user))
   if Employee.objects.filter(user=user).exclude(pk=employee.pk).exists():raise ValidationError('User is already linked to another employee.')
   if employee.user_id and employee.user_id!=user.pk:raise ValidationError('Employee already has a linked login.')
  return Response(self.data(provision_user(request,data,employee=employee,existing=user)))
class PermissionViewSet(viewsets.ViewSet):
 serializer_class=PermissionCatalogSerializer
 permission_classes=[AccessPermission];required_permission='access.roles.manage'
 def list(self,request):return Response(list(Permission.objects.values('code','module','resource','action')))
class MyPermissionsViewSet(viewsets.ViewSet):
 serializer_class=MyPermissionsSerializer
 permission_classes=[]
 def list(self,request):
  if not request.user.is_authenticated or not request.user.organization_id:raise PermissionDenied('Sign in to an organization account.')
  return Response({'permissions':effective_permissions(request.user),'scope':scope(request.user),'locations':list(location_ids(request.user))})
class AuditViewSet(viewsets.ViewSet):
 serializer_class=AuditSerializer
 permission_classes=[AccessPermission];required_permission='access.audit.view'
 def list(self,request):return Response(list(PermissionAuditLog.objects.filter(organization=request.user.organization).order_by('-created_at').values('id','action','target','actor__username','before','after','created_at')[:200]))
class BranchAssignmentViewSet(UserViewSet):
 def list(self,request):return Response([{'userId':u.pk,'username':u.username,'branches':list(u.branchAssignments.values_list('branch_id',flat=True))} for u in self.qs()])
class RoleOptionsViewSet(viewsets.ViewSet):
 serializer_class=RoleOptionSerializer
 permission_classes=[AccessPermission];required_permission='access.users.manage'
 def list(self,request):
  rows=[]
  for role in Role.objects.filter(organization=request.user.organization).order_by('name'):
   try:grantable(request.user,role)
   except PermissionDenied:continue
   rows.append({'id':role.pk,'name':role.name,'scope':role.scope})
  return Response(rows)
class BranchOptionsViewSet(viewsets.ViewSet):
 serializer_class=BranchOptionSerializer
 permission_classes=[AccessPermission];required_permission='access.users.manage'
 def list(self,request):
  qs=Location.objects.filter(organization=request.user.organization,kind='Branch',status='active')
  if scope(request.user)!='organization':qs=qs.filter(pk__in=location_ids(request.user))
  return Response(list(qs.values('id','name')))

class EmployeeOptionsViewSet(viewsets.ViewSet):
 permission_classes=[AccessPermission];required_permission='access.users.manage'
 serializer_class=UserAccessSerializer
 def list(self,request):
  from apps.hrms.models import Employee
  from .access import employee_ids
  qs=Employee.objects.filter(pk__in=employee_ids(request.user)).select_related('designation','branch','user').order_by('name')
  search=request.query_params.get('search','').strip()
  if search:
   from django.db.models import Q
   qs=qs.filter(Q(name__icontains=search)|Q(employeeCode__icontains=search)|Q(phone__icontains=search)|Q(email__icontains=search))
  from apps.hrms.views import Pagination
  pagination=Pagination();page=pagination.paginate_queryset(qs,request)
  return pagination.get_paginated_response([dict(id=e.pk,employeeCode=e.employeeCode,name=e.name,email=e.email,phone=e.phone,designationName=e.designation.name,branchName=e.branch.name,branch=e.branch_id,user=e.user_id,userName=e.user.username if e.user else '',userVisible=bool(e.user_id and (scope(request.user)=='organization' or e.user.branchAssignments.filter(branch_id__in=location_ids(request.user)).exists()))) for e in page])
