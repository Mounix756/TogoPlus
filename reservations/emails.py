from django.conf import settings
from django.core.mail import send_mail


def send_reservation_payment_email(reservation, payment_url):
    subject = f'Votre lien de paiement pour {reservation.resource.name}'
    message = f"""Bonjour {reservation.customer_name},

Votre demande de réservation a été vérifiée pour :

Ressource : {reservation.resource.name}
Début : {reservation.start_datetime:%d/%m/%Y %H:%M}
Fin : {reservation.end_datetime:%d/%m/%Y %H:%M}
Participants : {reservation.attendees_count}
Montant : {reservation.total_amount} XOF

Pour confirmer la réservation, ouvrez ce lien et procédez au paiement :
{payment_url}

Ce lien est temporaire. Si le créneau devient indisponible avant le paiement, la réservation ne sera pas confirmée.

Gamedzi-Rent
"""
    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        [reservation.customer_email],
        fail_silently=False,
    )
