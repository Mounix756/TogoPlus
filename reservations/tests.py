from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from .fedapay import (
    FedaPayError,
    build_merchant_reference,
    extract_reservation_token,
    extract_payment_url,
    extract_transaction_id,
    get_checkout_amount,
    forget_payment_attempt,
    get_payment_attempt,
    remember_payment_attempt,
    validate_transaction_matches_reservation,
)
from .models import Availability, Reservation, Resource
from .views import _build_payment_result_context


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
                    'amount': 100,
                    'status': 'pending',
                }
            }
        }

        self.assertEqual(extract_transaction_id(data), 987)

    def test_extract_transaction_id_accepts_documented_top_level_response(self):
        data = {
            'id': 654,
            'reference': 'txn_ref_123',
            'amount': 100,
            'status': 'pending',
        }

        self.assertEqual(extract_transaction_id(data), 654)

    def test_extract_transaction_id_accepts_v1_transaction_payload(self):
        data = {
            'v1/transaction': {
                'id': 7450,
                'reference': '1530805389377',
                'amount': 100,
                'status': 'pending',
            }
        }

        self.assertEqual(extract_transaction_id(data), 7450)

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
            'amount': str(get_checkout_amount(self.reservation.total_amount)),
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

    def test_payment_attempt_is_cached_by_reservation_token(self):
        reservation_token = 'reservation-token-demo'
        transaction_data = {
            'id': 987,
            'reference': 'txn_ref_987',
            'amount': 100,
            'status': 'pending',
        }

        remember_payment_attempt(reservation_token, transaction_data)

        self.assertEqual(
            get_payment_attempt(reservation_token),
            {
                'transaction_id': '987',
                'reference': 'txn_ref_987',
                'status': 'pending',
                'merchant_reference': '',
                'charge_amount': '100',
            },
        )

        forget_payment_attempt(reservation_token)
        self.assertEqual(get_payment_attempt(reservation_token), {})

    def test_validate_transaction_matches_reservation_rejects_missing_metadata(self):
        transaction = {
            'id': 987,
            'amount': 100,
            'status': 'approved',
        }

        with self.assertRaises(FedaPayError):
            validate_transaction_matches_reservation(transaction, self.reservation)

    def test_extract_reservation_token_reads_custom_metadata(self):
        token = 'encrypted-token-demo'
        transaction = {
            'id': 987,
            'amount': 15000,
            'status': 'approved',
            'custom_metadata': {
                'reservation_token': token,
            },
        }

        self.assertEqual(extract_reservation_token(transaction), token)

    def test_build_merchant_reference_is_deterministic(self):
        token = 'encrypted-token-demo'

        self.assertEqual(
            build_merchant_reference(token),
            build_merchant_reference(token),
        )

    def test_get_checkout_amount_uses_test_amount_setting(self):
        self.assertEqual(get_checkout_amount(self.reservation.total_amount), Decimal('100'))


class PaymentResultContextTests(SimpleTestCase):
    def test_build_payment_result_context_for_cancelled_payment(self):
        context = _build_payment_result_context('token-demo', 'canceled')

        self.assertEqual(context['payment_title'], 'Paiement annulé')
        self.assertIn('annulé', context['payment_error'])
        self.assertTrue(context['retry_url'])

    def test_build_payment_result_context_for_pending_payment(self):
        context = _build_payment_result_context('token-demo', 'pending')

        self.assertEqual(context['payment_title'], 'Paiement en attente')
        self.assertEqual(context['payment_alert_class'], 'info')
        self.assertEqual(context['retry_url'], '')
