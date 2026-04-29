from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Count, Q, Sum
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView

from .forms import ReservationBackofficeForm, ReservationForm, ResourceForm
from .models import Payment, Reservation, Resource, ResourceCategory


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
            reservation = form.save()
            messages.success(request, 'Votre demande de réservation a bien été enregistrée.')
            return redirect('reservations:reservation_success', pk=reservation.pk)

        context = self.get_context_data(form=form)
        messages.error(request, 'Veuillez corriger les informations du formulaire.')
        return self.render_to_response(context)


class ReservationSuccessView(DetailView):
    model = Reservation
    template_name = 'reservations/reservation_success.html'
    context_object_name = 'reservation'


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
