import logging

from fedapay import Webhook as FedaPayWebhook
from fedapay._error import SignatureVerificationError
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import ValidationError
from django.db import transaction as db_transaction
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView, View

from .emails import send_reservation_confirmation_email, send_reservation_payment_email
from .fedapay import (
    FedaPayClient,
    FedaPayError,
    build_merchant_reference,
    extract_checkout_amount,
    extract_transaction,
    extract_payment_url,
    extract_reservation_token,
    extract_transaction_id,
    extract_transaction_status,
    forget_payment_attempt,
    get_checkout_amount,
    get_payment_attempt,
    remember_payment_attempt,
    reservation_token_hash,
    validate_transaction_matches_reservation,
)
from .forms import ReservationBackofficeForm, ReservationForm, ResourceForm
from .models import Payment, Reservation, Resource, ResourceCategory
from .tokens import (
    ReservationTokenError,
    build_reservation_payment_token,
    load_reservation_from_token,
)


logger = logging.getLogger(__name__)


def _store_confirmed_reservation(token, transaction_data):
    transaction = extract_transaction(transaction_data)
    transaction_id = transaction.get('id')
    if not transaction_id:
        raise FedaPayError('La transaction FedaPay est invalide.')

    existing_payment = Payment.objects.filter(
        provider='FedaPay',
        provider_reference=str(transaction_id),
    ).select_related('reservation').first()
    if existing_payment:
        return existing_payment.reservation

    reservation = load_reservation_from_token(token)
    validate_transaction_matches_reservation(transaction, reservation)
    created_payment = None

    with db_transaction.atomic():
        reservation.status = Reservation.Status.CONFIRMED
        reservation.full_clean()
        reservation.save()
        created_payment = Payment.objects.create(
            reservation=reservation,
            amount=reservation.total_amount,
            currency=settings.FEDAPAY_CURRENCY,
            method=Payment.Method.OTHER,
            status=Payment.Status.SUCCEEDED,
            provider='FedaPay',
            provider_reference=str(transaction_id),
            paid_at=timezone.now(),
            metadata={
                'fedapay_status': transaction.get('status', ''),
                'fedapay_transaction_id': str(transaction_id),
                'fedapay_reference': transaction.get('reference', ''),
                'fedapay_receipt_url': transaction.get('receipt_url', ''),
                'fedapay_collected_amount': str(extract_checkout_amount(transaction)),
                'reservation_total_amount': str(reservation.total_amount),
                'reservation_token_hash': reservation_token_hash(token),
            },
        )
        db_transaction.on_commit(lambda: _send_confirmation_email_safely(created_payment.pk))

    return reservation


def _build_payment_result_context(token, payment_status, payment_error=None):
    normalized_status = (payment_status or 'unknown').lower()
    title = 'Paiement non confirmé'
    intro = 'La réservation n’a pas été enregistrée.'
    alert_class = 'warning'
    message = payment_error or 'Le paiement n’a pas été approuvé.'
    retry_url = reverse('reservations:reservation_payment', kwargs={'token': token})

    if normalized_status in {'canceled', 'cancelled'}:
        title = 'Paiement annulé'
        message = payment_error or (
            'Le paiement a été annulé avant confirmation. La réservation n’a pas été enregistrée.'
        )
    elif normalized_status in {'failed', 'declined', 'rejected'}:
        title = 'Paiement échoué'
        alert_class = 'danger'
        message = payment_error or (
            'Le paiement a échoué ou a été refusé. Vous pouvez relancer une nouvelle tentative.'
        )
    elif normalized_status in {'expired'}:
        title = 'Session expirée'
        message = payment_error or (
            'La session de paiement a expiré. Vous pouvez générer une nouvelle tentative.'
        )
    elif normalized_status in {'pending', 'processing'}:
        title = 'Paiement en attente'
        intro = 'La réservation n’est pas encore confirmée.'
        alert_class = 'info'
        message = payment_error or (
            'Le paiement est encore en cours de traitement. Revenez dans quelques instants.'
        )
        retry_url = ''
    elif normalized_status in {'unknown'}:
        title = 'Retour de paiement incomplet'
        message = payment_error or (
            'Le retour de paiement est incomplet. Vous pouvez réessayer ou contacter le support.'
        )

    return {
        'payment_title': title,
        'payment_intro': intro,
        'payment_status': normalized_status,
        'payment_error': message,
        'payment_alert_class': alert_class,
        'retry_url': retry_url,
    }


def _send_confirmation_email_safely(payment_id):
    try:
        payment = Payment.objects.select_related('reservation', 'reservation__resource').get(pk=payment_id)
        send_reservation_confirmation_email(payment)
    except Exception as exc:
        logger.warning('Echec envoi email de confirmation reservation %s: %s', payment_id, exc)


class FilteredPaginationMixin:
    def get_pagination_querystring(self):
        params = self.request.GET.copy()
        params.pop('page', None)
        return params.urlencode()


class HomeView(TemplateView):
    template_name = 'reservations/home.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        active_resources = Resource.objects.filter(is_active=True)
        context['featured_resources'] = (
            active_resources.select_related('category')
            .prefetch_related('availabilities')[:6]
        )
        context['categories'] = ResourceCategory.objects.filter(is_active=True)[:6]
        context['resource_count'] = active_resources.count()
        context['confirmed_count'] = Reservation.objects.filter(status=Reservation.Status.CONFIRMED).count()
        context['payment_ready_count'] = active_resources.filter(requires_payment=True).count()
        return context


class ResourceListView(FilteredPaginationMixin, ListView):
    model = Resource
    template_name = 'reservations/resource_list.html'
    context_object_name = 'resources'
    paginate_by = 9

    def get_queryset(self):
        queryset = (
            Resource.objects.filter(is_active=True)
            .select_related('category')
            .prefetch_related('availabilities')
        )
        query = self.request.GET.get('q', '').strip()
        resource_type = self.request.GET.get('type', '').strip()
        category = self.request.GET.get('category', '').strip()

        if query:
            queryset = queryset.filter(
                Q(name__icontains=query)
                | Q(description__icontains=query)
                | Q(location__icontains=query)
            )
        if resource_type:
            queryset = queryset.filter(resource_type=resource_type)
        if category:
            queryset = queryset.filter(category__slug=category)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['categories'] = ResourceCategory.objects.filter(is_active=True)
        context['resource_types'] = Resource.ResourceType.choices
        context['filters'] = {
            'q': self.request.GET.get('q', ''),
            'type': self.request.GET.get('type', ''),
            'category': self.request.GET.get('category', ''),
        }
        context['querystring'] = self.get_pagination_querystring()
        return context


class ResourceDetailView(DetailView):
    model = Resource
    template_name = 'reservations/resource_detail.html'
    context_object_name = 'resource'
    slug_field = 'slug'
    slug_url_kwarg = 'slug'

    def get_queryset(self):
        return (
            Resource.objects.filter(is_active=True)
            .select_related('category', 'manager')
            .prefetch_related('availabilities', 'unavailable_periods')
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault(
            'form',
            ReservationForm(
                resource=self.object,
                user=self.request.user,
            ),
        )
        context['upcoming_unavailable_periods'] = self.object.unavailable_periods.filter(
            ends_at__gte=timezone.now()
        )[:5]
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        form = ReservationForm(
            request.POST,
            resource=self.object,
            user=request.user,
        )
        if form.is_valid():
            reservation = form.save(commit=False)
            try:
                reservation.full_clean()
            except ValidationError as exc:
                form.add_error(None, exc)
                context = self.get_context_data(form=form)
                return self.render_to_response(context)

            token = build_reservation_payment_token(reservation)
            payment_url = request.build_absolute_uri(
                reverse('reservations:reservation_payment', kwargs={'token': token})
            )

            try:
                send_reservation_payment_email(reservation, payment_url)
            except Exception:
                form.add_error(
                    None,
                    'La réservation est disponible, mais l’email de paiement n’a pas pu être envoyé.',
                )
                context = self.get_context_data(form=form)
                return self.render_to_response(context)

            return redirect('reservations:reservation_email_sent')

        context = self.get_context_data(form=form)
        return self.render_to_response(context)


class ReservationEmailSentView(TemplateView):
    template_name = 'reservations/reservation_email_sent.html'


class ReservationPaymentView(TemplateView):
    template_name = 'reservations/reservation_payment.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        token = self.kwargs['token']
        context['token'] = token
        try:
            reservation = load_reservation_from_token(token)
            context['reservation'] = reservation
            context['checkout_amount'] = get_checkout_amount(reservation.total_amount)
            context['uses_test_checkout_amount'] = context['checkout_amount'] != reservation.total_amount
        except (ReservationTokenError, Resource.DoesNotExist, ValidationError) as exc:
            context['token_error'] = exc
        return context

    def post(self, request, *args, **kwargs):
        token = kwargs['token']
        try:
            reservation = load_reservation_from_token(token)
        except (ReservationTokenError, Resource.DoesNotExist, ValidationError) as exc:
            context = self.get_context_data(**kwargs)
            context['token_error'] = exc
            return self.render_to_response(context)

        if reservation.total_amount <= 0:
            context = self.get_context_data(**kwargs)
            context['payment_error'] = 'Le montant de cette réservation doit être supérieur à 0 XOF.'
            return self.render_to_response(context)

        callback_url = request.build_absolute_uri(
            reverse('reservations:fedapay_callback', kwargs={'token': token})
        )

        try:
            client = FedaPayClient()
            merchant_reference = build_merchant_reference(token)
            transaction_data = client.retrieve_transaction_by_merchant_reference(merchant_reference)
            if not transaction_data:
                transaction_data = client.create_transaction(
                    reservation,
                    callback_url,
                    reservation_token=token,
                    merchant_reference=merchant_reference,
                )
            transaction_id = extract_transaction_id(transaction_data)
            status = extract_transaction_status(transaction_data)
            remember_payment_attempt(token, transaction_data, merchant_reference=merchant_reference)

            if status == 'approved':
                callback_redirect_url = (
                    reverse('reservations:fedapay_callback', kwargs={'token': token})
                    + f'?id={transaction_id}&status=approved'
                )
                return redirect(callback_redirect_url)

            payment_link_data = client.create_payment_link(transaction_id)
            return redirect(extract_payment_url(payment_link_data))
        except FedaPayError as exc:
            context = self.get_context_data(**kwargs)
            context['payment_error'] = exc
            return self.render_to_response(context)


class FedaPayCallbackView(TemplateView):
    template_name = 'reservations/payment_result.html'

    def get(self, request, *args, **kwargs):
        token = kwargs['token']
        transaction_id = request.GET.get('id')
        callback_status = (request.GET.get('status') or '').lower()
        transaction_data = None
        payment_attempt = get_payment_attempt(token)

        if not transaction_id:
            transaction_id = payment_attempt.get('transaction_id')

        try:
            client = FedaPayClient()
            if transaction_id:
                transaction_data = client.retrieve_transaction(transaction_id)
            else:
                merchant_reference = payment_attempt.get('merchant_reference') or build_merchant_reference(token)
                transaction_data = client.retrieve_transaction_by_merchant_reference(merchant_reference)
                if transaction_data:
                    transaction_id = extract_transaction_id(transaction_data)
        except FedaPayError as exc:
            return self.render_to_response(
                _build_payment_result_context(
                    token,
                    callback_status or 'unknown',
                    str(exc),
                )
            )

        if not transaction_id or not transaction_data:
            return self.render_to_response(
                _build_payment_result_context(
                    token,
                    callback_status or 'unknown',
                    (
                        'Le retour de paiement ne contient pas d’identifiant exploitable et '
                        'aucune transaction correspondante n’a été retrouvée.'
                    ),
                )
            )

        status = extract_transaction_status(transaction_data)
        if status != 'approved':
            return self.render_to_response(
                _build_payment_result_context(
                    token,
                    status,
                    'Le paiement n’est pas approuvé. La réservation n’a pas été enregistrée.',
                )
            )

        try:
            reservation = _store_confirmed_reservation(token, transaction_data)
        except (FedaPayError, ReservationTokenError, Resource.DoesNotExist, ValidationError) as exc:
            return self.render_to_response(
                _build_payment_result_context(
                    token,
                    status,
                    str(exc),
                )
            )

        forget_payment_attempt(token)
        return redirect('reservations:reservation_success', pk=reservation.pk)


@method_decorator(csrf_exempt, name='dispatch')
class FedaPayWebhookView(View):
    def post(self, request, *args, **kwargs):
        if not settings.FEDAPAY_WEBHOOK_SECRET:
            return HttpResponse('Webhook FedaPay non configure.', status=503)

        signature = request.headers.get('X-FEDAPAY-SIGNATURE', '')
        if not signature:
            return HttpResponse('Signature webhook manquante.', status=400)

        try:
            event = FedaPayWebhook.construct_event(
                request.body,
                signature,
                settings.FEDAPAY_WEBHOOK_SECRET,
            )
        except (ValueError, SignatureVerificationError):
            return HttpResponse('Signature webhook invalide.', status=400)

        event_name = event.get('name') or event.get('type') or ''
        transaction = extract_transaction(event)
        if not transaction:
            logger.warning('Webhook FedaPay sans transaction exploitable: %s', event)
            return HttpResponse(status=200)

        token = extract_reservation_token(transaction)
        if not token:
            logger.warning('Webhook FedaPay sans reservation_token exploitable: %s', transaction)
            return HttpResponse(status=200)

        status = transaction.get('status') or ''
        if event_name != 'transaction.approved' and status != 'approved':
            return HttpResponse(status=200)

        try:
            _store_confirmed_reservation(token, transaction)
        except (FedaPayError, ReservationTokenError, Resource.DoesNotExist, ValidationError) as exc:
            logger.warning('Echec traitement webhook FedaPay: %s', exc)
            return HttpResponse(status=200)

        forget_payment_attempt(token)
        return HttpResponse(status=200)


class ReservationSuccessView(DetailView):
    model = Reservation
    template_name = 'reservations/reservation_success.html'
    context_object_name = 'reservation'

    def get_queryset(self):
        return Reservation.objects.select_related('resource').prefetch_related('payments')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        payment = self.object.payments.first()
        context['latest_payment'] = payment
        if payment and payment.metadata:
            context['fedapay_collected_amount'] = payment.metadata.get('fedapay_collected_amount')
        return context


class StaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    login_url = '/admin/login/'

    def test_func(self):
        return self.request.user.is_staff


class BackofficeDashboardView(StaffRequiredMixin, TemplateView):
    template_name = 'reservations/backoffice/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        now = timezone.now()
        reservations = Reservation.objects.select_related('resource')
        payments = Payment.objects.select_related('reservation')

        status_labels = dict(Reservation.Status.choices)
        status_counts = reservations.values('status').annotate(total=Count('id')).order_by('status')

        context['total_resources'] = Resource.objects.count()
        context['active_resources'] = Resource.objects.filter(is_active=True).count()
        context['pending_reservations'] = reservations.filter(status=Reservation.Status.PENDING).count()
        context['confirmed_reservations'] = reservations.filter(status=Reservation.Status.CONFIRMED).count()
        context['upcoming_reservations'] = reservations.filter(
            status__in=Reservation.BLOCKING_STATUSES,
            start_datetime__gte=now,
        ).order_by('start_datetime')[:8]
        context['recent_reservations'] = reservations.order_by('-created_at')[:8]
        context['status_cards'] = [
            {'status': item['status'], 'label': status_labels.get(item['status'], item['status']), 'total': item['total']}
            for item in status_counts
        ]
        context['revenue'] = (
            payments.filter(status=Payment.Status.SUCCEEDED).aggregate(total=Sum('amount'))['total'] or 0
        )
        return context


class BackofficeResourceListView(FilteredPaginationMixin, StaffRequiredMixin, ListView):
    model = Resource
    template_name = 'reservations/backoffice/resource_list.html'
    context_object_name = 'resources'
    paginate_by = 15

    def get_queryset(self):
        queryset = Resource.objects.select_related('category', 'manager')
        query = self.request.GET.get('q', '').strip()
        status = self.request.GET.get('status', '').strip()

        if query:
            queryset = queryset.filter(
                Q(name__icontains=query)
                | Q(location__icontains=query)
                | Q(category__name__icontains=query)
            )
        if status == 'active':
            queryset = queryset.filter(is_active=True)
        if status == 'inactive':
            queryset = queryset.filter(is_active=False)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['filters'] = {
            'q': self.request.GET.get('q', ''),
            'status': self.request.GET.get('status', ''),
        }
        context['querystring'] = self.get_pagination_querystring()
        return context


class BackofficeResourceCreateView(StaffRequiredMixin, CreateView):
    model = Resource
    form_class = ResourceForm
    template_name = 'reservations/backoffice/resource_form.html'
    success_url = reverse_lazy('reservations:backoffice_resources')

    def form_valid(self, form):
        messages.success(self.request, 'La ressource a été créée.')
        return super().form_valid(form)


class BackofficeResourceUpdateView(StaffRequiredMixin, UpdateView):
    model = Resource
    form_class = ResourceForm
    template_name = 'reservations/backoffice/resource_form.html'
    success_url = reverse_lazy('reservations:backoffice_resources')

    def form_valid(self, form):
        messages.success(self.request, 'La ressource a été mise à jour.')
        return super().form_valid(form)


class BackofficeReservationListView(FilteredPaginationMixin, StaffRequiredMixin, ListView):
    model = Reservation
    template_name = 'reservations/backoffice/reservation_list.html'
    context_object_name = 'reservations'
    paginate_by = 20

    def get_queryset(self):
        queryset = Reservation.objects.select_related('resource', 'user')
        query = self.request.GET.get('q', '').strip()
        status = self.request.GET.get('status', '').strip()

        if query:
            queryset = queryset.filter(
                Q(customer_name__icontains=query)
                | Q(customer_email__icontains=query)
                | Q(customer_phone__icontains=query)
                | Q(resource__name__icontains=query)
            )
        if status:
            queryset = queryset.filter(status=status)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['statuses'] = Reservation.Status.choices
        context['filters'] = {
            'q': self.request.GET.get('q', ''),
            'status': self.request.GET.get('status', ''),
        }
        context['querystring'] = self.get_pagination_querystring()
        return context


class BackofficeReservationUpdateView(StaffRequiredMixin, UpdateView):
    model = Reservation
    form_class = ReservationBackofficeForm
    template_name = 'reservations/backoffice/reservation_form.html'

    def get_success_url(self):
        return reverse('reservations:backoffice_reservations')

    def form_valid(self, form):
        messages.success(self.request, 'La réservation a été mise à jour.')
        return super().form_valid(form)


class ContactView(TemplateView):
    template_name = 'reservations/contact.html'


class BackofficePaymentListView(FilteredPaginationMixin, StaffRequiredMixin, ListView):
    model = Payment
    template_name = 'reservations/backoffice/payment_list.html'
    context_object_name = 'payments'
    paginate_by = 20

    def get_queryset(self):
        queryset = Payment.objects.select_related('reservation', 'reservation__resource')
        query = self.request.GET.get('q', '').strip()
        status = self.request.GET.get('status', '').strip()

        if query:
            queryset = queryset.filter(
                Q(provider_reference__icontains=query)
                | Q(provider__icontains=query)
                | Q(reservation__customer_name__icontains=query)
                | Q(reservation__customer_email__icontains=query)
            )
        if status:
            queryset = queryset.filter(status=status)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['statuses'] = Payment.Status.choices
        context['filters'] = {
            'q': self.request.GET.get('q', ''),
            'status': self.request.GET.get('status', ''),
        }
        context['querystring'] = self.get_pagination_querystring()
        return context
