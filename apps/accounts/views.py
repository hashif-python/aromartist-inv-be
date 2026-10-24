from drf_spectacular.utils import extend_schema
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes
from django.core.mail import send_mail
from rest_framework import generics, permissions, serializers
from rest_framework.exceptions import PermissionDenied, AuthenticationFailed, ValidationError
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.utils import get_md5_hash_password
from rest_framework_simplejwt.settings import api_settings
from .serializers import *

def cookie(response,token):
    response.set_cookie('perfumosol_refresh',str(token),max_age=86400,httponly=True,secure=settings.JWT_COOKIE_SECURE,samesite='Strict',path='/api/')
    return response

def check_origin(request):
    if request.headers.get('Origin') not in settings.CORS_ALLOWED_ORIGINS:
        raise PermissionDenied('Cookie authentication requires an allowed frontend Origin.')

class Login(generics.GenericAPIView):
    def get_authenticate_header(self,request): return "Bearer"
    serializer_class=LoginSerializer
    permission_classes=[permissions.AllowAny]
    authentication_classes=[]
    throttle_classes=[ScopedRateThrottle];throttle_scope='login'
    @extend_schema(responses=LoginResponseSerializer)
    def post(self,request):
        s=self.get_serializer(data=request.data);s.is_valid(raise_exception=True)
        u=authenticate(username=s.validated_data['username'],password=s.validated_data['password'])
        if not u or not u.organization_id: raise AuthenticationFailed('Invalid credentials or missing organization assignment.')
        t=RefreshToken.for_user(u)
        return cookie(Response({'access':str(t.access_token),'user':ProfileSerializer(u).data}),t)

class Refresh(generics.GenericAPIView):
    def get_authenticate_header(self,request): return "Bearer"
    serializer_class=TokenRefreshSerializer
    permission_classes=[permissions.AllowAny]
    authentication_classes=[]
    @extend_schema(responses=AccessResponseSerializer)
    def post(self,request):
        token=request.data.get('refresh')
        if not token:
            check_origin(request);token=request.COOKIES.get('perfumosol_refresh')
        try:
            parsed=RefreshToken(token)
            user=get_user_model().objects.get(pk=parsed[api_settings.USER_ID_CLAIM],is_active=True)
            if parsed.get(api_settings.REVOKE_TOKEN_CLAIM)!=get_md5_hash_password(user.password): raise AuthenticationFailed('Password changed. Sign in again.')
        except (TokenError, get_user_model().DoesNotExist, KeyError, TypeError): raise AuthenticationFailed('Invalid or expired refresh token.')
        s=self.get_serializer(data={'refresh':token})
        try: s.is_valid(raise_exception=True)
        except TokenError as exc: raise InvalidToken(str(exc))
        data=s.validated_data.copy();new=data.pop('refresh',None)
        res=Response(data)
        return cookie(res,new) if new else res

class Logout(generics.GenericAPIView):
    serializer_class=LogoutSerializer
    permission_classes=[permissions.AllowAny]
    authentication_classes=[]
    def post(self,request):
        token=request.data.get('refresh')
        if not token and request.COOKIES.get('perfumosol_refresh'):
            check_origin(request);token=request.COOKIES['perfumosol_refresh']
        if token:
            try: RefreshToken(token).blacklist()
            except TokenError: pass
        res=Response({'detail':'Logged out.'});res.delete_cookie('perfumosol_refresh',path='/api/',samesite='Strict');return res

class Profile(generics.RetrieveUpdateAPIView):
    serializer_class=ProfileSerializer
    def get_object(self): return self.request.user
    def update(self,request,*args,**kwargs):
        if request.user.employees.exists() and set(request.data)&{'name','email','phone'}:raise ValidationError('Employee-linked name, email and phone are managed in the HR employee profile.')
        forbidden=set(request.data)&{'role','permissions','organization','branch','warehouse','branchId','warehouseId','is_superuser','is_staff'}
        if forbidden: raise ValidationError('Roles and location assignments are managed by an administrator.')
        return super().update(request,*args,**kwargs)

class PasswordChange(generics.GenericAPIView):
    serializer_class=PasswordSerializer
    def post(self,request):
        s=self.get_serializer(data=request.data);s.is_valid(raise_exception=True)
        if not request.user.check_password(s.validated_data['currentPassword']): raise ValidationError({'currentPassword':'Incorrect current password.'})
        validate_password(s.validated_data['newPassword'],request.user)
        request.user.set_password(s.validated_data['newPassword']);request.user.save()
        return Response({'detail':'Password changed. Sign in again.'})

class PasswordReset(generics.GenericAPIView):
    serializer_class=ResetSerializer;permission_classes=[permissions.AllowAny];authentication_classes=[]
    throttle_classes=[ScopedRateThrottle];throttle_scope='reset'
    def post(self,request):
        s=self.get_serializer(data=request.data);s.is_valid(raise_exception=True)
        for u in get_user_model().objects.filter(email__iexact=s.validated_data['email'],is_active=True):
            uid=urlsafe_base64_encode(force_bytes(u.pk));token=default_token_generator.make_token(u)
            send_mail('PerfumASol password reset',f'Reset your password: {settings.FRONTEND_URL}/reset-password?uid={uid}&token={token}',settings.DEFAULT_FROM_EMAIL,[u.email])
        return Response({'detail':'If this account exists, reset instructions have been sent.'})

class ResetConfirm(generics.GenericAPIView):
    serializer_class=ResetConfirmSerializer;permission_classes=[permissions.AllowAny];authentication_classes=[]
    def post(self,request):
        s=self.get_serializer(data=request.data);s.is_valid(raise_exception=True);data=s.validated_data
        try: u=get_user_model().objects.get(pk=urlsafe_base64_decode(data['uid']).decode(),is_active=True)
        except (ValueError,UnicodeDecodeError,get_user_model().DoesNotExist): raise ValidationError('Invalid reset link.')
        if not default_token_generator.check_token(u,data['token']): raise ValidationError('Invalid or expired reset link.')
        validate_password(data['newPassword'],u);u.set_password(data['newPassword']);u.save()
        return Response({'detail':'Password reset. You may now sign in.'})
