from rest_framework.routers import DefaultRouter
from .access_views import *
router=DefaultRouter()
for path,cls in [('employee-options',EmployeeOptionsViewSet),('role-options',RoleOptionsViewSet),('branch-options',BranchOptionsViewSet),('roles',RoleViewSet),('users',UserViewSet),('permissions',PermissionViewSet),('my-permissions',MyPermissionsViewSet),('audit',AuditViewSet),('branch-assignments',BranchAssignmentViewSet)]:router.register(path,cls,basename='access-'+path)
urlpatterns=router.urls
