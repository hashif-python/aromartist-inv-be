from rest_framework.views import exception_handler as drf_handler
from rest_framework.response import Response
from django.db import IntegrityError
from django.db.models.deletion import ProtectedError
from django.core.exceptions import ValidationError as DjangoValidationError

def exception_handler(exc, context):
    if isinstance(exc, ProtectedError):
        return Response({'detail':'This record is referenced by other records. Deactivate it instead.'},status=409)
    if isinstance(exc, IntegrityError):
        return Response({'detail':'A uniqueness or database constraint was violated.'},status=409)
    if isinstance(exc, DjangoValidationError):
        return Response({'detail':exc.messages},status=400)
    return drf_handler(exc,context)
