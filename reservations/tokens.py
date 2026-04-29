import base64
import hashlib
import json
from decimal import Decimal

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import Reservation, Resource


class ReservationTokenError(Exception):
    pass


def _fernet():
    secret = f'{settings.SECRET_KEY}:{settings.RESERVATION_TOKEN_SALT}'.encode()
    key = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
    return Fernet(key)


def encrypt_reservation_payload(payload):
    data = json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode()
    return _fernet().encrypt(data).decode()


def decrypt_reservation_payload(token, max_age=None):
    try:
        data = _fernet().decrypt(token.encode(), ttl=max_age)
        return json.loads(data.decode())
    except (InvalidToken, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ReservationTokenError('Le lien de paiement est invalide ou a expiré.') from exc


def _serialize_datetime(value):
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.isoformat()


def _parse_datetime(value):
    parsed = parse_datetime(value)
    if parsed is None:
        raise ReservationTokenError('Les dates de réservation sont invalides.')
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


def reservation_to_payload(reservation):
    return {
        'resource_id': reservation.resource_id,
        'resource_slug': reservation.resource.slug,
        'customer_name': reservation.customer_name,
        'customer_email': reservation.customer_email,
        'customer_phone': reservation.customer_phone,
        'start_datetime': _serialize_datetime(reservation.start_datetime),
        'end_datetime': _serialize_datetime(reservation.end_datetime),
        'attendees_count': reservation.attendees_count,
        'notes': reservation.notes,
        'total_amount': str(reservation.total_amount),
    }


def reservation_from_payload(payload):
    resource = Resource.objects.get(
        id=payload['resource_id'],
        slug=payload['resource_slug'],
        is_active=True,
    )
    reservation = Reservation(
        resource=resource,
        customer_name=payload['customer_name'],
        customer_email=payload['customer_email'],
        customer_phone=payload.get('customer_phone', ''),
        start_datetime=_parse_datetime(payload['start_datetime']),
        end_datetime=_parse_datetime(payload['end_datetime']),
        attendees_count=int(payload['attendees_count']),
        notes=payload.get('notes', ''),
        status=Reservation.Status.PENDING,
    )
    reservation.total_amount = reservation.calculate_total_amount()

    # Re-run full business validation every time the encrypted request is opened.
    try:
        reservation.full_clean()
    except ValidationError:
        raise
    return reservation


def build_reservation_payment_token(reservation):
    reservation.total_amount = reservation.calculate_total_amount()
    return encrypt_reservation_payload(reservation_to_payload(reservation))


def load_reservation_from_token(token):
    payload = decrypt_reservation_payload(
        token,
        max_age=settings.RESERVATION_PAYMENT_TOKEN_MAX_AGE,
    )
    return reservation_from_payload(payload)


def decimal_to_fedapay_amount(amount):
    return int(Decimal(amount))
