from rest_framework.routers import DefaultRouter
from .views import *
router=DefaultRouter()
custom={'payroll-periods':PeriodViewSet,'employees':EmployeeViewSet,'attendance':AttendanceViewSet,'leaves':LeaveViewSet,'salary-revisions':RevisionViewSet,'payroll':PayrollViewSet,'salary-advances':AdvanceViewSet,'documents':DocumentViewSet}
for route,model in MODELS.items():
 cls=custom.get(route) or type(model.__name__+'ViewSet',(HRViewSet,),{'queryset':model.objects.all(),'serializer_class':serializer_for(model),'resource':NAMES[route]})
 router.register(route,cls,basename='hrms-'+route)
router.register('dashboard',DashboardViewSet,basename='hrms-dashboard')
urlpatterns=router.urls
