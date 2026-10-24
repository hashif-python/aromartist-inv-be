"""Tenant-isolated Evolution API integration adapted from Fitque's WhatsApp architecture."""
import base64
import io
import os
import re
from urllib.parse import quote
import requests
from django.utils import timezone
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4
from xml.sax.saxutils import escape
from .models import WhatsAppConnection, WhatsAppInvoiceDelivery

def configuration():
    url=os.environ.get('WHATSAPP_API_BASE_URL','').strip().rstrip('/')
    key=os.environ.get('WHATSAPP_API_KEY','').strip()
    if not url.startswith('https://') or not key:
        raise ValueError('Configure WHATSAPP_API_BASE_URL (HTTPS) and WHATSAPP_API_KEY on the server.')
    return url,key

def request_provider(method,path,**kwargs):
    base,key=configuration()
    try:
        response=requests.request(method,base+path,headers={'apikey':key,'Content-Type':'application/json'},timeout=35,**kwargs)
    except requests.RequestException as exc:
        raise RuntimeError('Unable to reach WhatsApp provider.') from exc
    if not response.ok:
        raise RuntimeError(f'WhatsApp provider returned HTTP {response.status_code}.')
    try:return response.json()
    except ValueError:return {}

def get_connection(org):
    obj,_=WhatsAppConnection.objects.get_or_create(organization=org,defaults={'instance_name':f'perfumosol-{org.pk}'[:100]})
    return obj

def instance_path(obj):return quote(obj.instance_name,safe='')

def state(obj):
    data=request_provider('GET',f'/instance/connectionState/{instance_path(obj)}')
    instance=data.get('instance') or {}
    state=instance.get('state') or data.get('state') or 'close'
    return {'configured':True,'connected':str(state).lower()=='open','state':state,'instance_name':obj.instance_name,'auto_send':obj.auto_send}

def connect(obj):
    name=instance_path(obj)
    try:request_provider('GET',f'/instance/connectionState/{name}')
    except RuntimeError:
        request_provider('POST','/instance/create',json={'instanceName':obj.instance_name,'integration':'WHATSAPP-BAILEYS','qrcode':True})
    info=state(obj)
    if not info['connected']:
        qr=request_provider('GET',f'/instance/connect/{name}')
        value=qr.get('qrcode') or qr.get('qrCode') or qr.get('qr') or qr
        if isinstance(value,dict):value=value.get('base64') or value.get('code')
        info['qr']=value if isinstance(value,str) else None
    return info

def normalize_phone(value):
    digits=re.sub(r'\D','',str(value or ''))
    if len(digits)==10:digits='91'+digits
    if not 10<=len(digits)<=15:raise ValueError('Enter a valid international WhatsApp phone number.')
    return digits

def invoice_pdf(invoice):
    out=io.BytesIO();doc=SimpleDocTemplate(out,pagesize=A4,rightMargin=42,leftMargin=42,topMargin=42,bottomMargin=42)
    styles=getSampleStyleSheet();story=[Paragraph('AROMA ARTIST | TAX INVOICE',styles['Title']),Spacer(1,14)]
    for text in [f'Invoice: {invoice.invoiceNumber}',f'Date: {invoice.date}',f'Customer: {invoice.customerName}',f'Mobile: {invoice.customerMobile or "-"}']:
        story.append(Paragraph(escape(str(text)),styles['Normal']));story.append(Spacer(1,6))
    data=[['Product','Qty','Rate','Discount','Total']]
    for line in invoice.lines.all():data.append([str(line.productName)[:42],str(line.qty),str(line.rate),str(line.discount),str(line.total)])
    data += [['','','','Subtotal',str(invoice.subtotal)],['','','','Discount',str(invoice.discount)],['','','','Tax',str(invoice.tax)],['','','','TOTAL',str(invoice.total)]]
    table=Table(data,colWidths=[210,43,76,85,88],repeatRows=1,hAlign='LEFT');table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#172B4D')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('BOTTOMPADDING',(0,0),(-1,-1),8),('TOPPADDING',(0,0),(-1,-1),8),('LINEBELOW',(0,0),(-1,-1),.3,colors.lightgrey),('VALIGN',(0,0),(-1,-1),'TOP')]))
    story.extend([Spacer(1,18),table]);doc.build(story);return out.getvalue()

def send_invoice(obj,invoice,phone):
    phone=normalize_phone(phone)
    if not state(obj)['connected']:raise ValueError('WhatsApp is not connected.')
    delivery=WhatsAppInvoiceDelivery.objects.create(organization=invoice.organization,invoice=invoice,phone=phone,status='pending')
    try:
        pdf=base64.b64encode(invoice_pdf(invoice)).decode('ascii')
        result=request_provider('POST',f'/message/sendMedia/{instance_path(obj)}',json={'number':phone,'mediatype':'document','mimetype':'application/pdf','media':pdf,'fileName':f'Invoice-{invoice.invoiceNumber}.pdf','caption':f'Aroma Artist | Invoice {invoice.invoiceNumber} | Total INR {invoice.total}. Thank you for shopping with us!'})
        delivery.status='sent';delivery.provider_message_id=str((result.get('key') or {}).get('id') or result.get('id') or '')[:160];delivery.sent_at=timezone.now()
    except Exception as exc:
        delivery.status='failed';delivery.error=str(exc)[:500];delivery.save(update_fields=['status','error','updated_at']);raise
    delivery.save(update_fields=['status','provider_message_id','sent_at','updated_at'])
    return delivery
