import os
from pathlib import Path
from datetime import timedelta
BASE_DIR = Path(__file__).resolve().parents[2]
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'development-only-perfumosol-change-before-deploying')
DEBUG = os.environ.get('DJANGO_DEBUG', '1') == '1'
ALLOWED_HOSTS = os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')
INSTALLED_APPS = ['django.contrib.admin','django.contrib.auth','django.contrib.contenttypes','django.contrib.sessions','django.contrib.messages','django.contrib.staticfiles','corsheaders','rest_framework','rest_framework_simplejwt.token_blacklist','drf_spectacular','apps.accounts','apps.erp','apps.hrms']
MIDDLEWARE = [
    "apps.accounts.scope_context.PermissionScopeMiddleware",'django.middleware.security.SecurityMiddleware','whitenoise.middleware.WhiteNoiseMiddleware','corsheaders.middleware.CorsMiddleware','django.contrib.sessions.middleware.SessionMiddleware','django.middleware.common.CommonMiddleware','django.middleware.csrf.CsrfViewMiddleware','django.contrib.auth.middleware.AuthenticationMiddleware','django.contrib.messages.middleware.MessageMiddleware','django.middleware.clickjacking.XFrameOptionsMiddleware']
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{'BACKEND':'django.template.backends.django.DjangoTemplates','DIRS':[],'APP_DIRS':True,'OPTIONS':{'context_processors':['django.template.context_processors.request','django.contrib.auth.context_processors.auth','django.contrib.messages.context_processors.messages']}}]
WSGI_APPLICATION = 'config.wsgi.application'
DATABASES = {'default': {'ENGINE':'django.db.backends.postgresql','NAME':os.environ.get('POSTGRES_DB','perfumosol'),'USER':os.environ.get('POSTGRES_USER','perfumosol'),'PASSWORD':os.environ.get('POSTGRES_PASSWORD','local-development-only'),'HOST':os.environ.get('POSTGRES_HOST','db'),'PORT':os.environ.get('POSTGRES_PORT','5432'),'CONN_MAX_AGE':60}}
AUTH_USER_MODEL = 'accounts.User'
AUTH_PASSWORD_VALIDATORS = [{'NAME':'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},{'NAME':'django.contrib.auth.password_validation.MinimumLengthValidator'},{'NAME':'django.contrib.auth.password_validation.CommonPasswordValidator'},{'NAME':'django.contrib.auth.password_validation.NumericPasswordValidator'}]
LANGUAGE_CODE='en-us'
TIME_ZONE='Asia/Kolkata'
USE_I18N=True
USE_TZ=True
STATIC_URL='/static/'
STATIC_ROOT=BASE_DIR/'staticfiles'
MEDIA_URL='/media/'
MEDIA_ROOT=BASE_DIR/'media'
DEFAULT_AUTO_FIELD='django.db.models.BigAutoField'
CORS_ALLOWED_ORIGINS=os.environ.get('CORS_ALLOWED_ORIGINS','http://localhost:5173,http://127.0.0.1:5173').split(',')
CORS_ALLOW_CREDENTIALS=True
CSRF_TRUSTED_ORIGINS=CORS_ALLOWED_ORIGINS
SESSION_COOKIE_HTTPONLY=True
JWT_COOKIE_SECURE=os.environ.get('JWT_COOKIE_SECURE','0')=='1'
REST_FRAMEWORK={'DEFAULT_AUTHENTICATION_CLASSES':['rest_framework_simplejwt.authentication.JWTAuthentication'],'DEFAULT_PERMISSION_CLASSES':['rest_framework.permissions.IsAuthenticated'],'DEFAULT_SCHEMA_CLASS':'drf_spectacular.openapi.AutoSchema','COERCE_DECIMAL_TO_STRING':False,'DEFAULT_THROTTLE_RATES':{'login':'20/hour','reset':'5/hour'},'EXCEPTION_HANDLER':'apps.common.errors.exception_handler'}
SIMPLE_JWT={'ACCESS_TOKEN_LIFETIME':timedelta(minutes=10),'REFRESH_TOKEN_LIFETIME':timedelta(days=1),'ROTATE_REFRESH_TOKENS':False,'BLACKLIST_AFTER_ROTATION':False,'CHECK_REVOKE_TOKEN':True}
SPECTACULAR_SETTINGS={'TITLE':'PerfumASol ERP API','VERSION':'1.0.0','PREPROCESSING_HOOKS':['apps.common.schema.canonical_only'],'DESCRIPTION':'JWT protected ERP. Login sets an HttpOnly refresh cookie. Business totals and stock movements are calculated on the server.'}
EMAIL_BACKEND=os.environ.get('EMAIL_BACKEND','django.core.mail.backends.console.EmailBackend')
EMAIL_HOST=os.environ.get('EMAIL_HOST','')
EMAIL_PORT=int(os.environ.get('EMAIL_PORT','587'))
EMAIL_HOST_USER=os.environ.get('EMAIL_HOST_USER','')
EMAIL_HOST_PASSWORD=os.environ.get('EMAIL_HOST_PASSWORD','')
EMAIL_USE_TLS=True
DEFAULT_FROM_EMAIL=os.environ.get('DEFAULT_FROM_EMAIL','no-reply@localhost')
FRONTEND_URL=os.environ.get('FRONTEND_URL','http://localhost:5173')
LOGGING={'version':1,'disable_existing_loggers':False,'handlers':{'console':{'class':'logging.StreamHandler'}},'root':{'handlers':['console'],'level':'INFO'}}
