from .base import *
DATABASES={'default':{'ENGINE':'django.db.backends.sqlite3','NAME':os.environ.get('SQLITE_TEST_DATABASE',':memory:')}}
PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher']
ALLOWED_HOSTS=['testserver','localhost','127.0.0.1']
EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'
