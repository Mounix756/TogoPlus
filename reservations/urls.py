from django.urls import path

from . import views

app_name = 'reservations'

urlpatterns = [
    path('', views.HomeView.as_view(), name='home'),
    path('contact/', views.ContactView.as_view(), name='contact'),
    path('ressources/', views.ResourceListView.as_view(), name='resource_list'),
    path('ressources/<slug:slug>/', views.ResourceDetailView.as_view(), name='resource_detail'),
    path('reservations/<int:pk>/merci/', views.ReservationSuccessView.as_view(), name='reservation_success'),
    path('backoffice/', views.BackofficeDashboardView.as_view(), name='backoffice_dashboard'),
    path('backoffice/ressources/', views.BackofficeResourceListView.as_view(), name='backoffice_resources'),
    path('backoffice/ressources/ajouter/', views.BackofficeResourceCreateView.as_view(), name='backoffice_resource_create'),
    path('backoffice/ressources/<int:pk>/modifier/', views.BackofficeResourceUpdateView.as_view(), name='backoffice_resource_update'),
    path('backoffice/reservations/', views.BackofficeReservationListView.as_view(), name='backoffice_reservations'),
    path('backoffice/reservations/<int:pk>/modifier/', views.BackofficeReservationUpdateView.as_view(), name='backoffice_reservation_update'),
    path('backoffice/paiements/', views.BackofficePaymentListView.as_view(), name='backoffice_payments'),
]
