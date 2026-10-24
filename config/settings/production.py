from .base import *
if not os.environ.get('DJANGO_SECRET_KEY') or SECRET_KEY.startswith('development-only'):
    raise RuntimeError('Set a strong DJANGO_SECRET_KEY for production')
DEBUG=False
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
JWT_COOKIE_SECURE=True
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS=True
SECURE_HSTS_PRELOAD=True
SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO','https')
STORAGES={'default':{'BACKEND':'django.core.files.storage.FileSystemStorage'},'staticfiles':{'BACKEND':'whitenoise.storage.CompressedManifestStaticFilesStorage'}}
