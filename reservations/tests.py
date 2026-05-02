from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import QueryDict
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils.datastructures import MultiValueDict
from django.utils import timezone

from .emails import send_reservation_confirmation_email
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
from .forms import ResourceCategoryForm, ResourceForm, ResourceImagesUploadForm
from .invoices import build_invoice_filename, generate_invoice_pdf
from .models import Availability, Payment, Reservation, Resource, ResourceCategory, ResourceImage
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


@override_settings(MEDIA_ROOT='/tmp/e-reservation-test-media')
class ResourceBackofficeBehaviorTests(TestCase):
    tiny_gif = (
        b'GIF87a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00'
        b'\xff\xff\xff,\x00\x00\x00\x00\x01\x00\x01\x00'
        b'\x00\x02\x02D\x01\x00;'
    )

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='manager',
            email='manager@example.com',
            password='pass-test-123',
            is_staff=True,
        )

    def test_resource_form_assigns_connected_user_as_manager(self):
        form = ResourceForm(
            data={
                'name': 'Salle Togo+ Prestige',
                'category': '',
                'resource_type': Resource.ResourceType.ROOM,
                'description': 'Grande salle',
                'location': 'Lome',
                'capacity': 50,
                'price': '25000',
                'requires_payment': 'on',
            },
            user=self.user,
        )

        self.assertTrue(form.is_valid(), form.errors)
        resource = form.save()

        self.assertEqual(resource.manager, self.user)
        self.assertTrue(resource.is_active)
        self.assertEqual(resource.slug, 'salle-togo-prestige')

    def test_resource_slug_is_made_unique_automatically(self):
        Resource.objects.create(
            name='Salle Premium',
            slug='salle-premium',
            manager=self.user,
        )

        resource = Resource.objects.create(
            name='Salle Premium',
            slug='sera-remplace',
            manager=self.user,
        )

        self.assertEqual(resource.slug, 'salle-premium-2')

    def test_category_form_generates_slug_automatically(self):
        form = ResourceCategoryForm(
            data={
                'name': 'Salles VIP',
                'description': 'Espaces premium pour événements.',
                'is_active': 'on',
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        category = form.save()

        self.assertEqual(category.slug, 'salles-vip')
        self.assertTrue(category.is_active)

    def test_category_slug_is_made_unique_automatically(self):
        ResourceCategory.objects.create(name='Salles VIP', slug='salles-vip')

        category = ResourceCategory.objects.create(name='Salles-vip', slug='sera-remplace')

        self.assertEqual(category.slug, 'salles-vip-2')

    def test_category_backoffice_crud_keeps_resources_when_category_is_deleted(self):
        self.client.force_login(self.user)

        create_response = self.client.post(
            reverse('reservations:backoffice_category_create'),
            data={
                'name': 'Conférences',
                'description': 'Salles et services pour conférences.',
                'is_active': 'on',
            },
        )

        self.assertRedirects(create_response, reverse('reservations:backoffice_categories'))
        category = ResourceCategory.objects.get(name='Conférences')
        resource = Resource.objects.create(
            category=category,
            name='Salle Conférence A',
            slug='salle-conference-a',
            manager=self.user,
        )

        list_response = self.client.get(reverse('reservations:backoffice_categories'))

        self.assertContains(list_response, 'Conférences')
        self.assertContains(
            list_response,
            reverse('reservations:backoffice_category_update', kwargs={'pk': category.pk}),
        )
        self.assertContains(
            list_response,
            reverse('reservations:backoffice_category_delete', kwargs={'pk': category.pk}),
        )

        update_response = self.client.post(
            reverse('reservations:backoffice_category_update', kwargs={'pk': category.pk}),
            data={
                'name': 'Conférences Pro',
                'description': 'Salles et services pour événements professionnels.',
            },
        )

        self.assertRedirects(update_response, reverse('reservations:backoffice_categories'))
        category.refresh_from_db()
        self.assertEqual(category.name, 'Conférences Pro')
        self.assertEqual(category.slug, 'conferences-pro')
        self.assertFalse(category.is_active)

        confirm_response = self.client.get(
            reverse('reservations:backoffice_category_delete', kwargs={'pk': category.pk})
        )

        self.assertContains(confirm_response, 'Confirmer la suppression')
        self.assertContains(confirm_response, '1 ressource(s) associée(s)')

        delete_response = self.client.post(
            reverse('reservations:backoffice_category_delete', kwargs={'pk': category.pk})
        )

        self.assertRedirects(delete_response, reverse('reservations:backoffice_categories'))
        self.assertFalse(ResourceCategory.objects.filter(pk=category.pk).exists())
        resource.refresh_from_db()
        self.assertIsNone(resource.category)

    def test_backoffice_logout_uses_project_route_and_logs_user_out(self):
        self.client.force_login(self.user)

        base_response = self.client.get(reverse('reservations:backoffice_dashboard'))

        self.assertContains(base_response, reverse('reservations:backoffice_logout'))
        self.assertNotContains(base_response, reverse('admin:logout'))

        logout_response = self.client.post(reverse('reservations:backoffice_logout'))

        self.assertRedirects(logout_response, reverse('reservations:home'))
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_resource_create_view_uses_single_multiple_image_input(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('reservations:backoffice_resource_create'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="resource-images-input"')
        self.assertContains(response, 'multiple')
        self.assertNotContains(response, 'Image 1')

    def test_resource_list_displays_delete_action(self):
        resource = Resource.objects.create(
            name='Salle à supprimer',
            slug='salle-a-supprimer',
            manager=self.user,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse('reservations:backoffice_resources'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            reverse('reservations:backoffice_resource_delete', kwargs={'pk': resource.pk}),
        )

    def test_resource_delete_view_deletes_resource_and_images(self):
        resource = Resource.objects.create(
            name='Studio à supprimer',
            slug='studio-a-supprimer',
            manager=self.user,
        )
        resource_image = ResourceImage.objects.create(
            resource=resource,
            image=self._image_upload('delete-me.gif'),
        )
        image_storage = resource_image.image.storage
        image_name = resource_image.image.name
        self.client.force_login(self.user)

        response = self.client.get(
            reverse('reservations:backoffice_resource_delete', kwargs={'pk': resource.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Confirmer la suppression')
        self.assertTrue(image_storage.exists(image_name))

        response = self.client.post(
            reverse('reservations:backoffice_resource_delete', kwargs={'pk': resource.pk})
        )

        self.assertRedirects(response, reverse('reservations:backoffice_resources'))
        self.assertFalse(Resource.objects.filter(pk=resource.pk).exists())
        self.assertFalse(ResourceImage.objects.filter(pk=resource_image.pk).exists())
        self.assertFalse(image_storage.exists(image_name))

    def test_resource_delete_view_keeps_resource_with_reservations(self):
        resource = Resource.objects.create(
            name='Salle protégée',
            slug='salle-protegee',
            manager=self.user,
        )
        Reservation.objects.create(
            resource=resource,
            customer_name='Client Historique',
            customer_email='historique@example.com',
            start_datetime=timezone.make_aware(datetime(2026, 6, 1, 9, 0)),
            end_datetime=timezone.make_aware(datetime(2026, 6, 1, 12, 0)),
            status=Reservation.Status.CONFIRMED,
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('reservations:backoffice_resource_delete', kwargs={'pk': resource.pk})
        )

        self.assertRedirects(response, reverse('reservations:backoffice_resources'))
        self.assertTrue(Resource.objects.filter(pk=resource.pk).exists())

    def test_resource_image_limit_is_enforced(self):
        resource = Resource.objects.create(
            name='Studio Photo',
            slug='studio-photo',
            manager=self.user,
        )
        for index in range(4):
            ResourceImage.objects.create(
                resource=resource,
                image=SimpleUploadedFile(
                    f'image-{index}.jpg',
                    b'filecontent',
                    content_type='image/jpeg',
                ),
                sort_order=index + 1,
            )

        extra_image = ResourceImage(
            resource=resource,
            image=SimpleUploadedFile(
                'image-5.jpg',
                b'filecontent',
                content_type='image/jpeg',
            ),
        )

        with self.assertRaises(ValidationError):
            extra_image.full_clean()

    def test_resource_images_upload_form_accepts_multiple_images_from_single_field(self):
        form = ResourceImagesUploadForm(
            data={},
            files=MultiValueDict(
                {
                    'images': [
                        self._image_upload('image-1.gif'),
                        self._image_upload('image-2.gif'),
                    ]
                }
            ),
            current_image_ids=[],
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(len(form.cleaned_data['images']), 2)

    def test_resource_images_upload_form_keeps_four_images_max_after_deletions(self):
        data = QueryDict('', mutable=True)
        data.setlist('delete_images', ['2'])
        form = ResourceImagesUploadForm(
            data=data,
            files=MultiValueDict(
                {
                    'images': [
                        self._image_upload('new-1.gif'),
                        self._image_upload('new-2.gif'),
                    ]
                }
            ),
            current_image_ids=[1, 2, 3],
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_delete_image_ids, {2})

    def test_resource_images_upload_form_rejects_more_than_four_images(self):
        form = ResourceImagesUploadForm(
            data={},
            files=MultiValueDict(
                {
                    'images': [
                        self._image_upload('new-1.gif'),
                        self._image_upload('new-2.gif'),
                    ]
                }
            ),
            current_image_ids=[1, 2, 3],
        )

        self.assertFalse(form.is_valid())
        self.assertIn('Une ressource ne peut pas contenir plus de 4 images.', form.non_field_errors())

    def _image_upload(self, name):
        return SimpleUploadedFile(name, self.tiny_gif, content_type='image/gif')


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class ReservationConfirmationEmailTests(TestCase):
    def setUp(self):
        self.resource = Resource.objects.create(
            name='Salle Signature',
            slug='salle-signature',
            capacity=100,
            price=Decimal('25000.00'),
            requires_payment=True,
        )
        self.reservation = Reservation.objects.create(
            resource=self.resource,
            customer_name='Ama Lawson',
            customer_email='ama@example.com',
            customer_phone='+22890000000',
            start_datetime=timezone.make_aware(datetime(2026, 5, 15, 9, 0)),
            end_datetime=timezone.make_aware(datetime(2026, 5, 15, 18, 0)),
            attendees_count=80,
            status=Reservation.Status.CONFIRMED,
            total_amount=Decimal('25000.00'),
        )
        self.payment = Payment.objects.create(
            reservation=self.reservation,
            amount=Decimal('25000.00'),
            currency='XOF',
            method=Payment.Method.OTHER,
            status=Payment.Status.SUCCEEDED,
            provider='FedaPay',
            provider_reference='TEST-PAYMENT-001',
            metadata={
                'fedapay_reference': 'FDP-001',
                'fedapay_collected_amount': '100',
            },
        )

    def test_generate_invoice_pdf_returns_pdf_document(self):
        pdf_content = generate_invoice_pdf(self.payment)

        self.assertTrue(pdf_content.startswith(b'%PDF'))

    def test_send_reservation_confirmation_email_attaches_invoice_pdf(self):
        send_reservation_confirmation_email(self.payment)

        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]
        self.assertIn('Confirmation de reservation', sent_email.subject)
        self.assertEqual(len(sent_email.attachments), 1)

        attachment = sent_email.attachments[0]
        self.assertEqual(attachment[0], build_invoice_filename(self.payment))
        self.assertEqual(attachment[2], 'application/pdf')
        self.assertTrue(attachment[1].startswith(b'%PDF'))
