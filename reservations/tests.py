from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from .models import Reservation, Resource


class ReservationModelTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='client',
            email='client@example.com',
            password='pass-test-123',
        )
        self.resource = Resource.objects.create(
            name='Salle de conférence',
            slug='salle-conference',
            capacity=20,
        )

    def test_reservation_rejects_overlapping_slot(self):
        starts_at = timezone.now() + timedelta(days=1)
        ends_at = starts_at + timedelta(hours=2)

        Reservation.objects.create(
            resource=self.resource,
            user=self.user,
            customer_name='Client Test',
            customer_email='client@example.com',
            start_datetime=starts_at,
            end_datetime=ends_at,
            status=Reservation.Status.CONFIRMED,
        )

        reservation = Reservation(
            resource=self.resource,
            customer_name='Autre Client',
            customer_email='autre@example.com',
            start_datetime=starts_at + timedelta(minutes=30),
            end_datetime=ends_at + timedelta(minutes=30),
        )

        with self.assertRaises(ValidationError):
            reservation.full_clean()

    def test_reservation_accepts_adjacent_slot(self):
        starts_at = timezone.now() + timedelta(days=1)
        ends_at = starts_at + timedelta(hours=2)

        Reservation.objects.create(
            resource=self.resource,
            customer_name='Client Test',
            customer_email='client@example.com',
            start_datetime=starts_at,
            end_datetime=ends_at,
            status=Reservation.Status.CONFIRMED,
        )

        reservation = Reservation(
            resource=self.resource,
            customer_name='Autre Client',
            customer_email='autre@example.com',
            start_datetime=ends_at,
            end_datetime=ends_at + timedelta(hours=1),
        )

        reservation.full_clean()
