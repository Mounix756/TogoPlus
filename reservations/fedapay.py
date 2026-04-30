import json
import logging
import hashlib
from decimal import Decimal, InvalidOperation
from urllib.parse import quote
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.cache import cache


logger = logging.getLogger(__name__)


class FedaPayError(Exception):
    pass


class FedaPayClient:
    def __init__(self):
        self.base_url = settings.FEDAPAY_API_BASE_URL.rstrip('/')
        self.secret_key = settings.FEDAPAY_SECRET_KEY
        if not self.secret_key:
            raise FedaPayError('Le paiement en ligne n’est pas configuré pour le moment.')

    def _request(self, method, path, payload=None, allow_404=False):
        url = f'{self.base_url}{path}'
        body = None
        headers = {
            'Authorization': f'Bearer {self.secret_key}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
        if payload is not None:
            body = json.dumps(payload).encode()

        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=20) as response:
                data = response.read().decode()
        except HTTPError as exc:
            if allow_404 and exc.code == 404:
                return None
            error_body = exc.read().decode(errors='ignore')
            logger.warning('FedaPay HTTP error %s on %s %s: %s', exc.code, method, path, error_body)
            raise FedaPayError(
                'Le prestataire de paiement a refusé la demande. Veuillez réessayer ou contacter le support.'
            ) from exc
        except URLError as exc:
            logger.warning('FedaPay network error on %s %s: %s', method, path, exc)
            raise FedaPayError('Impossible de joindre le prestataire de paiement pour le moment.') from exc

        if not data:
            return {}

        try:
            return json.loads(data)
        except json.JSONDecodeError as exc:
            logger.warning('Invalid FedaPay response on %s %s: %s', method, path, data)
            raise FedaPayError('La réponse du prestataire de paiement est invalide.') from exc

    def create_transaction(self, reservation, callback_url, reservation_token=None, merchant_reference=None):
        customer = {
            'email': reservation.customer_email,
            'firstname': reservation.customer_name.split(' ', 1)[0],
            'lastname': reservation.customer_name.split(' ', 1)[1]
            if ' ' in reservation.customer_name
            else reservation.customer_name,
        }
        if reservation.customer_phone:
            customer['phone_number'] = {
                'number': reservation.customer_phone,
                'country': 'TG',
            }

        custom_metadata = {
            'resource_id': reservation.resource_id,
            'resource_slug': reservation.resource.slug,
            'start_datetime': reservation.start_datetime.isoformat(),
            'end_datetime': reservation.end_datetime.isoformat(),
        }
        if reservation_token:
            custom_metadata['reservation_token'] = reservation_token
            custom_metadata['reservation_token_hash'] = reservation_token_hash(reservation_token)

        payload = {
            'description': f'Réservation {reservation.resource.name} - {reservation.customer_email}',
            'amount': int(get_checkout_amount(reservation.total_amount)),
            'currency': {'iso': settings.FEDAPAY_CURRENCY},
            'callback_url': callback_url,
            'customer': customer,
            'custom_metadata': custom_metadata,
        }
        if merchant_reference:
            payload['merchant_reference'] = merchant_reference
        return self._request('POST', '/transactions', payload)

    def create_payment_link(self, transaction_id):
        return self._request('POST', f'/transactions/{transaction_id}/token')

    def retrieve_transaction(self, transaction_id):
        return self._request('GET', f'/transactions/{transaction_id}')

    def retrieve_transaction_by_merchant_reference(self, merchant_reference):
        path = f'/transactions/merchant/{quote(str(merchant_reference), safe="")}'
        return self._request('GET', path, allow_404=True)


def remember_payment_attempt(reservation_token, transaction_data, merchant_reference=''):
    transaction = extract_transaction(transaction_data)
    transaction_id = transaction.get('id')
    if not transaction_id:
        logger.warning(
            'Unable to cache FedaPay payment attempt because transaction id is missing: %s',
            summarize_payload(transaction_data),
        )
        return

    cache.set(
        _payment_attempt_cache_key(reservation_token),
        {
            'transaction_id': str(transaction_id),
            'reference': transaction.get('reference', ''),
            'status': transaction.get('status', ''),
            'merchant_reference': merchant_reference or transaction.get('merchant_reference', ''),
            'charge_amount': str(extract_checkout_amount(transaction)),
        },
        timeout=settings.FEDAPAY_TRANSACTION_CACHE_TIMEOUT,
    )


def get_payment_attempt(reservation_token):
    attempt = cache.get(_payment_attempt_cache_key(reservation_token))
    if isinstance(attempt, dict):
        return attempt
    return {}


def forget_payment_attempt(reservation_token):
    cache.delete(_payment_attempt_cache_key(reservation_token))


TRANSACTION_MARKERS = {
    'amount',
    'status',
    'reference',
    'callback_url',
    'custom_metadata',
    'merchant_reference',
}


def extract_transaction(data):
    if isinstance(data, dict):
        if data.get('id') and (TRANSACTION_MARKERS & data.keys()):
            return data

        for key in ('transaction', 'data', 'object', 'record', 'result', 'v1/transaction'):
            value = data.get(key)
            transaction = extract_transaction(value)
            if transaction:
                return transaction

        for value in data.values():
            transaction = extract_transaction(value)
            if transaction:
                return transaction

        if data.get('id'):
            return data
        return {}

    if isinstance(data, list):
        for item in data:
            transaction = extract_transaction(item)
            if transaction:
                return transaction
    return {}


def extract_transaction_id(data):
    if isinstance(data, dict) and data.get('id') not in (None, ''):
        return data.get('id')

    transaction = extract_transaction(data)
    transaction_id = transaction.get('id')
    if not transaction_id:
        logger.warning(
            'Unexpected FedaPay transaction payload without id: %s',
            summarize_payload(data),
        )
        raise FedaPayError('Le prestataire de paiement n’a pas retourné d’identifiant de transaction.')
    return transaction_id


def extract_payment_url(data):
    url = extract_nested_value(data, 'url')
    if not url:
        raise FedaPayError('Le prestataire de paiement n’a pas retourné de lien de paiement.')
    return url


def extract_transaction_status(data):
    return extract_transaction(data).get('status')


def extract_reservation_token(data):
    transaction = extract_transaction(data)
    metadata = transaction.get('custom_metadata') or transaction.get('metadata') or {}
    if not isinstance(metadata, dict):
        return None
    token = metadata.get('reservation_token')
    if isinstance(token, str) and token:
        return token
    return None


def extract_nested_value(data, key):
    if isinstance(data, dict):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
        for nested_value in data.values():
            found = extract_nested_value(nested_value, key)
            if found:
                return found
    elif isinstance(data, list):
        for item in data:
            found = extract_nested_value(item, key)
            if found:
                return found
    return None


def validate_transaction_matches_reservation(transaction, reservation):
    amount = _decimal_from_transaction_value(transaction.get('amount'))
    if amount is None:
        raise FedaPayError(
            'La vérification du paiement est incomplète. La réservation n’a pas été enregistrée.'
        )

    expected_amount = get_checkout_amount(reservation.total_amount)
    if amount != expected_amount:
        raise FedaPayError(
            'Le montant confirmé ne correspond pas à cette réservation. La réservation n’a pas été enregistrée.'
        )

    currency = transaction.get('currency')
    currency_iso = None
    if isinstance(currency, dict):
        currency_iso = currency.get('iso') or currency.get('code')
    elif isinstance(currency, str):
        currency_iso = currency

    if currency_iso and currency_iso.upper() != settings.FEDAPAY_CURRENCY.upper():
        raise FedaPayError(
            'La devise confirmée ne correspond pas à cette réservation. La réservation n’a pas été enregistrée.'
        )

    metadata = transaction.get('custom_metadata') or transaction.get('metadata') or {}
    if not isinstance(metadata, dict):
        metadata = {}
    if not metadata:
        raise FedaPayError(
            'La vérification de sécurité du paiement est incomplète. La réservation n’a pas été enregistrée.'
        )

    expected_metadata = {
        'resource_id': str(reservation.resource_id),
        'resource_slug': reservation.resource.slug,
        'start_datetime': reservation.start_datetime.isoformat(),
        'end_datetime': reservation.end_datetime.isoformat(),
    }
    for key, expected_value in expected_metadata.items():
        current_value = metadata.get(key)
        if str(current_value) != expected_value:
            raise FedaPayError(
                'Les informations confirmées par le paiement ne correspondent pas à cette réservation.'
            )


def _decimal_from_transaction_value(value):
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def get_checkout_amount(real_amount):
    configured_amount = _decimal_from_transaction_value(settings.FEDAPAY_TEST_CHARGE_AMOUNT)
    if configured_amount is not None and configured_amount > 0:
        return configured_amount
    return Decimal(real_amount)


def extract_checkout_amount(transaction):
    amount = _decimal_from_transaction_value(transaction.get('amount'))
    if amount is not None:
        return amount
    return Decimal('0')


def _payment_attempt_cache_key(reservation_token):
    return f'fedapay:payment-attempt:{reservation_token}'


def summarize_payload(data, limit=600):
    try:
        rendered = json.dumps(data, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        rendered = repr(data)
    if len(rendered) <= limit:
        return rendered
    return f'{rendered[:limit]}...'


def build_merchant_reference(reservation_token):
    digest = hashlib.sha256(reservation_token.encode()).hexdigest()[:24].upper()
    return f'TOGOPLUS-{digest}'


def reservation_token_hash(reservation_token):
    return hashlib.sha256(reservation_token.encode()).hexdigest()
