from django.http import HttpResponse
from django.db import transaction
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError, NotFound
from .models import Invoice, WhatsAppInvoiceDelivery
from .whatsapp_service import get_connection, state, connect, request_provider, instance_path, send_invoice, invoice_pdf
from apps.accounts.permissions import has

class WhatsAppAPI(APIView):
    permission_classes=[IsAuthenticated]
    def check(self,request,admin=False):
        if not request.user.organization_id:raise PermissionDenied('Organization required.')
        if not has(request.user,*(['*'] if admin else ['sales.view','sales.pos','pos.access','sales.invoice.checkout','*'])):raise PermissionDenied('Insufficient permissions.')
        return get_connection(request.user.organization)
    def get(self,request,action):
        obj=self.check(request,admin=action!='status')
        if action!='status':raise NotFound()
        try:return Response(state(obj))
        except (RuntimeError,ValueError) as exc:return Response({'configured':False,'connected':False,'state':'unavailable','detail':str(exc),'auto_send':obj.auto_send})
    def post(self,request,action):
        obj=self.check(request,admin=True)
        try:
            if action=='connect':return Response(connect(obj))
            if action=='disconnect':
                request_provider('DELETE',f'/instance/logout/{instance_path(obj)}');return Response({'connected':False,'state':'close'})
            if action=='settings':
                value=request.data.get('auto_send')
                if not isinstance(value,bool):raise ValidationError({'auto_send':'Boolean required.'})
                obj.auto_send=value;obj.save(update_fields=['auto_send','updated_at']);return Response({'auto_send':value})
        except (RuntimeError,ValueError) as exc:raise ValidationError({'detail':str(exc)})
        raise NotFound()

class WhatsAppInvoiceAPI(APIView):
    permission_classes=[IsAuthenticated]
    def invoice(self,request,pk):
        if not has(request.user,'sales.view','sales.pos','pos.access','sales.invoice.checkout','*'):raise PermissionDenied()
        try:return Invoice.objects.prefetch_related('lines').get(pk=pk,organization=request.user.organization)
        except Invoice.DoesNotExist:raise NotFound('Invoice not found.')
    def get(self,request,pk,action):
        invoice=self.invoice(request,pk)
        if action=='pdf':return HttpResponse(invoice_pdf(invoice),content_type='application/pdf',headers={'Content-Disposition':f'attachment; filename="Invoice-{invoice.invoiceNumber}.pdf"'})
        if action=='status':return Response(list(WhatsAppInvoiceDelivery.objects.filter(invoice=invoice,organization=request.user.organization).order_by('-created_at').values('id','phone','status','sent_at','error')[:20]))
        raise NotFound()
    def post(self,request,pk,action):
        if action!='send':raise NotFound()
        invoice=self.invoice(request,pk)
        phone=request.data.get('phone') or invoice.customerMobile
        if not phone:raise ValidationError({'phone':'Invoice has no customer phone. Enter a WhatsApp number.'})
        from .whatsapp_service import normalize_phone
        try: phone=normalize_phone(phone)
        except ValueError as exc: raise ValidationError({'phone':str(exc)})
        # Serialize attempts for the same invoice; never resend an already sent PDF.
        with transaction.atomic():
            invoice=Invoice.objects.select_for_update().get(pk=invoice.pk,organization=request.user.organization)
            previous=WhatsAppInvoiceDelivery.objects.filter(invoice=invoice,organization=request.user.organization,phone=phone,status='sent').order_by('-created_at').first()
            if previous:return Response({'status':'sent','delivery_id':previous.pk,'phone':phone,'already_sent':True})
            try:delivery=send_invoice(get_connection(request.user.organization),invoice,phone)
            except (RuntimeError,ValueError) as exc:raise ValidationError({'detail':str(exc)})
            return Response({'status':delivery.status,'delivery_id':delivery.id,'phone':delivery.phone})

