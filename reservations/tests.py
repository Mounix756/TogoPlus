from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from .fedapay import (
    FedaPayError,
    extract_payment_url,
    extract_transaction_id,
    validate_transaction_matches_reservation,
)
from .models import Availability, Reservation, Resource


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

    def test_reservation_accepts_multi_day_slot_without_existing_overlap(self):
        reservation = Reservation(
            resource=self.resource,
            customer_name='Client Multi-jours',
            customer_email='multi@example.com',
            start_datetime=timezone.make_aware(datetime(2026, 5, 4, 9, 0)),
            end_datetime=timezone.make_aware(datetime(2026, 5, 5, 17, 0)),
            attendees_count=12,
        )

        reservation.full_clean()
        self.assertEqual(reservation.billable_days, 2)

    def test_reservation_ignores_configured_availability_when_no_overlap_exists(self):
        Availability.objects.create(
            resource=self.resource,
            weekday=0,
            start_time=time(9, 0),
            end_time=time(12, 0),
        )

        reservation = Reservation(
            resource=self.resource,
            customer_name='Client Flexible',
            customer_email='flexible@example.com',
            start_datetime=timezone.make_aware(datetime(2026, 5, 4, 8, 0)),
            end_datetime=timezone.make_aware(datetime(2026, 5, 4, 17, 0)),
            attendees_count=12,
        )

        reservation.full_clean()


class FedaPayHelpersTests(TestCase):
    def setUp(self):
        self.resource = Resource.objects.create(
            name='Salle premium',
            slug='salle-premium',
            capacity=40,
            price=Decimal('15000.00'),
            requires_payment=True,
        )
        self.reservation = Reservation(
            resource=self.resource,
            customer_name='Client Paiement',
            customer_email='client@example.com',
            start_datetime=timezone.make_aware(datetime(2026, 5, 4, 9, 0)),
            end_datetime=timezone.make_aware(datetime(2026, 5, 4, 17, 0)),
            attendees_count=20,
        )
        self.reservation.total_amount = self.reservation.calculate_total_amount()

    def test_extract_transaction_id_accepts_nested_transaction_response(self):
        data = {
            'data': {
                'transaction': {
                    'id': 987,
                    'amount': 15000,
                    'status': 'pending',
                }
            }
        }

        self.assertEqual(extract_transaction_id(data), 987)

    def test_extract_payment_url_accepts_nested_token_response(self):
        data = {
            'data': {
                'token': {
                    'url': 'https://pay.example.test/secure',
                }
            }
        }

        self.assertEqual(extract_payment_url(data), 'https://pay.example.test/secure')

    def test_validate_transaction_matches_reservation_requires_amount_and_metadata(self):
        transaction = {
            'id': 987,
            'amount': 15000,
            'status': 'approved',
            'custom_metadata': {
                'resource_id': str(self.resource.pk),
                'resource_slug': self.resource.slug,
                'start_datetime': self.reservation.start_datetime.isoformat(),
                'end_datetime': self.reservation.end_datetime.isoformat(),
            },
        }

        validate_transaction_matches_reservation(transaction, self.reservation)

    def test_validate_transaction_matches_reservation_rejects_amount_mismatch(self):
        transaction = {
            'id': 987,
            'amount': 1000,
            'status': 'approved',
            'custom_metadata': {
                'resource_id': str(self.resource.pk),
                'resource_slug': self.resource.slug,
                'start_datetime': self.reservation.start_datetime.isoformat(),
                'end_datetime': self.reservation.end_datetime.isoformat(),
            },
        }

        with self.assertRaises(FedaPayError):
            validate_transaction_matches_reservation(transaction, self.reservation)

    def test_validate_transaction_matches_reservation_rejects_missing_metadata(self):
        transaction = {
            'id': 987,
            'amount': 15000,
            'status': 'approved',
        }

        with self.assertRaises(FedaPayError):
            validate_transaction_matches_reservation(transaction, self.reservation)
