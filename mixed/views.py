# encoding: utf-8

from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate
from smtplib import SMTP

from six.moves.urllib.parse import urlencode

from django.conf import settings
from django.core.context_processors import csrf
from django.core.urlresolvers import reverse
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.http.response import HttpResponseBadRequest, HttpResponse
from django.shortcuts import render_to_response, redirect, get_object_or_404
from django.utils.translation import ugettext as _
from django.views.decorators.csrf import csrf_exempt

from markdown2 import markdown

from .models import Document, EmailAccount
from .forms import DocumentForm, UserCreationForm
from .server_list_converter import convert_server_list
from .custom_converter import convert_customizable


@login_required
def document_create(request):
    if request.method == 'GET':
        content = {
            'form': DocumentForm(),
            'title': 'Create',
            'username': request.user.username,
        }
        content.update(csrf(request))
        return render_to_response('doc_editor.html', content)

    elif request.method == 'POST':
        form = DocumentForm(request.POST)

        if not form.is_valid():
            content = {
                'form': form,
                'title': 'Create',
                'username': request.user.username,
            }
            content.update(csrf(request))
            return render_to_response('doc_editor.html', content)

        form.instance.user = request.user
        form.save()

        return redirect(reverse('list'))


def doc_owner_required(function):
    def _doc_owner_required(request, slug):
        try:
            document = Document.objects.get(slug=slug, is_deleted=False)
        except Document.DoesNotExist:
            message = 'Document %s not exists or maybe deleted.' % slug
            return redirect('%s?%s' % (reverse('list'), urlencode({'message': message})))

        if document.user and request.user.id != document.user.id:
            message = 'You have no authority to do this action to <%s>.' % document.name
            return redirect('%s?%s' % (reverse('list'), urlencode({'message': message.encode('utf-8')})))

        request.document = document
        return function(request, slug)
    return _doc_owner_required


@login_required
@doc_owner_required
def document_edit(request, slug):
    if request.method == 'GET':
        document = request.document
        form = DocumentForm(instance=document)

        content = {'form': form, 'title': document.name, 'username': request.user.username,}
        content.update(csrf(request))

        return render_to_response('doc_editor.html', content)

    elif request.method == 'POST':
        document = request.document
        form = DocumentForm(request.POST, instance=document)

        if not form.is_valid():
            content = {
                'form': form,
                'title': document.name,
                'username': request.user.username,
            }
            content.update(csrf(request))
            return render_to_response('doc_editor.html', content)

        form.save()

        return redirect(reverse('list'))


@login_required
@doc_owner_required
def document_delete(request, slug):
    message = None
    try:
        document = request.document
        if document.converter != 'S':
            document.is_deleted = True
            document.save()
        else:
            message = 'Server list cannot be deleted.'
            return redirect('%s?%s' % (reverse('list'), urlencode({'message': message})))
    except Document.DoesNotExist:
        pass

    return redirect(reverse('list'))


def document_list(request):
    doc_list = Document.objects.filter(is_deleted=False)

    content = {
        'doc_list': [
            {
                'name': doc.name,
                'slug': doc.slug,
            }
            for doc in doc_list
        ],
        'required': request.GET.get('required'),
        'message': request.GET.get('message'),
        'username': request.user.username,
    }

    return render_to_response('doc_list.html', content)


def document_view(request, slug):
    try:
        document = Document.objects.get(slug=slug, is_deleted=False)
    except Document.DoesNotExist:
        return redirect('%s?%s' % (reverse('list'), urlencode({'required': slug})))

    doc_context = document.context
    server_list = None
    customized_context = None

    if document.converter == 'N':
        pass  # normal context, output directly.
    elif document.converter == 'S':
        server_list, doc_context = convert_server_list(doc_context)
    elif document.custom_converter:
        customized_context, doc_context = convert_customizable(doc_context, document.custom_converter)

    content = {
        'title': document.name,
        'slug': document.slug,
        'server_list': server_list,
        'customized': customized_context,
        'paragraphs': [p2 for p2 in [p for p in doc_context.split('\n')] if p2.strip() != ''],
        'username': request.user.username,
    }

    return render_to_response('doc.html', content)


def register(request):
    if request.method == 'GET':
        content = {
            'form': UserCreationForm,
        }
        content.update(csrf(request))
        return render_to_response('registration/register.html', content)

    elif request.method == 'POST':
        form = UserCreationForm(request.POST)
        if not form.is_valid():
            content = {
                'form': form,
            }
            content.update(csrf(request))
            return render_to_response('registration/register.html', content)

        form.save()

        user = authenticate(
            username=form.cleaned_data['username'],
            password=form.cleaned_data['password1'])
        login(request, user)

        return redirect(reverse('list'))


SUBJECT, TEXT = 0, 1
MAIL_LIST = {
    'overtime': [
        _('[overtime] %(name)s %(date)s for %(period)s hour(s)'),
        '',
    ],
    'dayoff': [
        _('[dayoff] %(name)s %(date)s for %(period)s hour(s)'),
        '',
    ],
    'outwork': [
        _('[outwork] %(name)s %(date)s for %(period)s hour(s)'),
        '',
    ],
}


MANAGER_ADDRESS = getattr(settings, 'MANAGER_ADDRESS', '')
FRONTEND_ADDRESS = getattr(settings, 'FRONTEND_ADDRESS', '')
CFO_ADDRESS = getattr(settings, 'CFO_ADDRESS', '')
PUBLIC_MANMAIL_ACCOUNT = getattr(settings, 'PUBLIC_MANMAIL_ACCOUNT', None)
@csrf_exempt
@login_required
def send_manmail(request):
    user = request.user

    context = {
        'username': user.username,
    }

    if request.method == 'GET':
        if hasattr(user, 'manmail'):
            m_sender = user.manmail.email
            m_sign = user.manmail.sign
        else:
            m_sender = ''
            m_sign = ''

        now = datetime.now()
        ringout_time = datetime(now.year, now.month, now.day, 17, 30)
        m_period = (now - ringout_time).total_seconds()
        if m_period < 0: m_period = 0
        m_period = str(float(int(m_period / 1800)) / 2)

        context.update({
            'm_period': m_period,
            'm_content': 'KH88888 KH00012',
            'm_receiver': MANAGER_ADDRESS,
            'm_sender': m_sender,
            'm_name': user.first_name + user.last_name,
            'm_sign': m_sign,
        })

        return render_to_response('manmail.html', context=context)

    m_type = request.POST.get('m_type')
    m_period = request.POST.get('m_period')
    subject_dt = request.POST.get('m_date', datetime.now())
    m_sender = request.POST.get('m_sender', '').strip()
    m_name = request.POST.get('m_name', '').strip()
    m_sign = request.POST.get('m_sign')

    context.update({
        'm_receiver': MANAGER_ADDRESS,
        'm_period': m_period,
        'm_sender': m_sender,
        'm_name': user.first_name + user.last_name,
        'm_sign': m_sign,
        'm_content': request.POST.get('m_context', ''),
    })

    messages = []
    if m_type not in MAIL_LIST:
        messages.append(_('Invalid mail type.'))
    try:
        v_period = float(m_period)
        if m_type == 'overtime' and int(v_period * 10) % 5 != 0:
            messages.append(_('Invalid period, The minimize unit is half an hour.'))
    except:
        messages.append(_('Invalid period.'))

    if not subject_dt:
        subject_dt = datetime.now()
    if isinstance(subject_dt, datetime):
        subject_dt = subject_dt.strftime('%Y%m%d')
    else:
        try:
            datetime.strptime(subject_dt, '%Y%m%d')
        except ValueError:
            messages.append(_('Invalid date format, should in format `yyyymmdd`.'))
            # context.update({'message': _('Invalid date format, should in format `yyyymmdd`.')})
            # return render_to_response('manmail.html', context=context)
    if messages:
        context.update({'message': u' | '.join(messages)})
        return render_to_response('manmail.html', context=context)

    if not m_sender:
        messages.append(_('Please input your sender mail address.'))
    if not m_name:
        messages.append(_('Please input your name.'))
    if messages:
        context.update({'message': u' | '.join(messages)})
        return render_to_response('manmail.html', context=context)

    m_account, is_created = EmailAccount.objects.get_or_create(user=user)
    if is_created:
        m_account.email = m_sender
        m_account.sign = m_sign
        m_account.save()
    else:
        if m_account.email != m_sender:
            m_account.email = m_sender
        if m_account.sign != m_sign:
            m_account.sign = m_sign
        m_account.save()
    if not m_account.password:
        m_account = PUBLIC_MANMAIL_ACCOUNT

    if m_name != user.first_name + user.last_name:
        user.first_name = m_name[0]
        user.last_name = m_name[1:]
        user.save()

    mail_template = MAIL_LIST[m_type]

    to_addrs = [MANAGER_ADDRESS]
    cc_addrs = [FRONTEND_ADDRESS, m_sender]
    if m_type == 'dayoff' and float(m_period) >= 24:
        cc_addrs.append(CFO_ADDRESS)
    to_addrs += cc_addrs

    message = MIMEMultipart()
    message['Subject'] = mail_template[SUBJECT] % {
        'name': m_name,
        'date': subject_dt,
        'period': m_period,
    }
    message['From'] = m_sender
    message['To'] = MANAGER_ADDRESS
    message['Cc'] = ','.join(cc_addrs)
    message['Date'] = formatdate(localtime=True)

    m_context = request.POST.get('m_context', mail_template[TEXT])
    m_sign = m_sign.replace('\r\n', '\n').replace('\n', '\n\n')
    m_context = '\n\n'.join([m_context, m_sign])
    context = MIMEText(markdown(m_context), _subtype='html', _charset='utf-8')
    message.attach(context)

    try:
        smtp = SMTP(m_account.smtp_server)
        smtp.login(m_account.email, m_account.password)
        smtp.sendmail(m_account.email, to_addrs, message.as_string())
    except Exception as ex:
        print ex.message
        HttpResponseBadRequest(
            'Send mail failed, please retry again if you donot wanna to give up.')
    finally:
        smtp.close()

    # return HttpResponse('send mail successed!')
    return render_to_response('manmail_ok.html')


DEFAULT_SMTP_SERVER = getattr(settings, 'DEFAULT_SMTP_SERVER', 'smtp.163.com')
@login_required
def set_manmail_account(request):
    email = request.GET.get('email')
    password = request.GET.get('psw')
    smtp_server = request.GET.get('smtp', DEFAULT_SMTP_SERVER)
    if not (email and password):
        return HttpResponseBadRequest('Lack of email or password information.')

    user = request.user

    if not hasattr(user, 'manmail'):
        m_account = EmailAccount(
            email=email,
            password=password,
            smtp_server=smtp_server,
            user=request.user)
    else:
        m_account = user.manmail
        m_account.email = email
        m_account.password = password
        m_account.smtp_server = smtp_server
    m_account.save()
    return HttpResponse('set email account succeed!')


def set_manmail_page(request):
    return render_to_response('manmail.html')
