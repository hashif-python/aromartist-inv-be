from django.urls import path
from .views import Login, Mobile

urlpatterns = [
    path("login/", Login.as_view()),
    path("<str:section>/", Mobile.as_view()),
    path("<str:section>/<str:pk>/", Mobile.as_view()),
]
