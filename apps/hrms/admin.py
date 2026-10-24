from django.contrib import admin
from .serializers import MODELS
for model in MODELS.values():admin.site.register(model)
