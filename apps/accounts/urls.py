from django.urls import path
from .views import *
urlpatterns=[path('login/',Login.as_view()),path('logout/',Logout.as_view()),path('token/refresh/',Refresh.as_view()),path('refresh/',Refresh.as_view()),path('me/',Profile.as_view()),path('profile/',Profile.as_view()),path('password/change/',PasswordChange.as_view()),path('password/reset/',PasswordReset.as_view()),path('password/reset/confirm/',ResetConfirm.as_view())]
