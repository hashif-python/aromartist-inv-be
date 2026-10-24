from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse
from django.db import connection
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

def health(request):
    try:
        with connection.cursor() as cur: cur.execute('SELECT 1')
        return JsonResponse({'status':'ok','database':'connected'})
    except Exception: return JsonResponse({'status':'unhealthy'},status=503)
urlpatterns=[path('api/v1/pos/mobile/',include('apps.pos.urls')),path('api/v1/hrms/',include('apps.hrms.urls')),path('api/v1/access/',include('apps.accounts.access_urls')),path('health/',health),path('admin/',admin.site.urls),path('api/schema/',SpectacularAPIView.as_view(),name='schema'),path('api/docs/',SpectacularSwaggerView.as_view(url_name='schema'),name='swagger-ui'),path('api/v1/auth/',include('apps.accounts.urls')),path('api/v1/',include('apps.promotions.urls')),path('api/v1/',include('apps.erp.urls')),path('api/auth/',include('apps.accounts.urls')),path('api/',include('apps.erp.urls'))]
