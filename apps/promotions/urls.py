from django.urls import path
from .views import Offers,OfferDetail,Preview
urlpatterns=[path("offers/",Offers.as_view()),path("offers/<str:pk>/",OfferDetail.as_view()),path("pos/offers/preview/",Preview.as_view())]
