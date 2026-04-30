from django.conf import settings
from django.core.mail import EmailMessage, send_mail

from .invoices import build_invoice_filename, build_invoice_number, generate_invoice_pdf


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


def send_reservation_confirmation_email(payment):
    reservation = payment.reservation
    invoice_number = build_invoice_number(payment)
    subject = f'Confirmation de reservation et facture - {reservation.resource.name}'
    message = f"""Bonjour {reservation.customer_name},

Votre paiement a ete confirme et votre reservation est maintenant enregistree.

Ressource : {reservation.resource.name}
Debut : {reservation.start_datetime:%d/%m/%Y %H:%M}
Fin : {reservation.end_datetime:%d/%m/%Y %H:%M}
Participants : {reservation.attendees_count}
Montant de reservation : {payment.amount} {payment.currency}
Numero de facture : {invoice_number}

Vous trouverez votre facture en piece jointe au format PDF.

Merci pour votre confiance.
{settings.INVOICE_COMPANY_NAME}
"""
    email = EmailMessage(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        [reservation.customer_email],
    )
    email.attach(
        build_invoice_filename(payment),
        generate_invoice_pdf(payment),
        'application/pdf',
    )
    email.send(fail_silently=False)
