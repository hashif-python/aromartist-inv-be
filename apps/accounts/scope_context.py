"""Request-local permission scope; mixed roles do not broaden unrelated resources."""
from contextvars import ContextVar
permission_context=ContextVar('permission_context',default=None)
class PermissionScopeMiddleware:
 def __init__(self,get_response):self.get_response=get_response
 def __call__(self,request):
  token=permission_context.set(None)
  try:return self.get_response(request)
  finally:permission_context.reset(token)
