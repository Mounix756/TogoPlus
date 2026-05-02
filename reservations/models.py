from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone
from django.utils.text import slugify


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class ResourceCategory(TimeStampedModel):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'catégorie de ressource'
        verbose_name_plural = 'catégories de ressources'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.slug = self._build_unique_slug()
        super().save(*args, **kwargs)

    def _build_unique_slug(self):
        base_slug = slugify(self.name)[:120] or 'categorie'
        candidate = base_slug
        suffix = 2
        queryset = ResourceCategory.objects.exclude(pk=self.pk)

        while queryset.filter(slug=candidate).exists():
            suffix_text = f'-{suffix}'
            candidate = f'{base_slug[:140 - len(suffix_text)]}{suffix_text}'
            suffix += 1

        return candidate


class Resource(TimeStampedModel):
    class ResourceType(models.TextChoices):
        ROOM = 'room', 'Salle'
        SERVICE = 'service', 'Service'
        EQUIPMENT = 'equipment', 'Équipement'

    category = models.ForeignKey(
        ResourceCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='resources',
    )
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=170, unique=True)
    resource_type = models.CharField(
        max_length=20,
        choices=ResourceType.choices,
        default=ResourceType.ROOM,
    )
    description = models.TextField(blank=True)
    location = models.CharField(max_length=180, blank=True)
    capacity = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        help_text='Nombre maximum de personnes acceptées.',
    )
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
        help_text='Prix de réservation du créneau.',
    )
    requires_payment = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    manager = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='managed_resources',
    )

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['resource_type', 'is_active']),
            models.Index(fields=['slug']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(capacity__gte=1),
                name='resource_capacity_positive',
            ),
        ]
        verbose_name = 'ressource'
        verbose_name_plural = 'ressources'

    def __str__(self):
        return self.name

    @property
    def primary_image(self):
        images = getattr(self, '_prefetched_objects_cache', {}).get('images')
        if images is not None:
            return images[0] if images else None
        return self.images.order_by('sort_order', 'id').first()

    def save(self, *args, **kwargs):
        self.slug = self._build_unique_slug()
        super().save(*args, **kwargs)

    def _build_unique_slug(self):
        base_slug = slugify(self.name)[:150] or 'ressource'
        candidate = base_slug
        suffix = 2
        queryset = Resource.objects.exclude(pk=self.pk)

        while queryset.filter(slug=candidate).exists():
            suffix_text = f'-{suffix}'
            candidate = f'{base_slug[:170 - len(suffix_text)]}{suffix_text}'
            suffix += 1

        return candidate


class ResourceImage(TimeStampedModel):
    MAX_IMAGES_PER_RESOURCE = 4

    resource = models.ForeignKey(
        Resource,
        on_delete=models.CASCADE,
        related_name='images',
    )
    image = models.ImageField(upload_to='resources/')
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']
        indexes = [
            models.Index(fields=['resource', 'sort_order']),
        ]
        verbose_name = 'image de ressource'
        verbose_name_plural = 'images de ressource'

    def __str__(self):
        return f'Image {self.resource.name} #{self.pk or "new"}'

    def clean(self):
        super().clean()
        if not self.resource_id:
            return

        queryset = ResourceImage.objects.filter(resource_id=self.resource_id)
        if self.pk:
            queryset = queryset.exclude(pk=self.pk)
        if queryset.count() >= self.MAX_IMAGES_PER_RESOURCE:
            raise ValidationError(
                f'Une ressource ne peut pas contenir plus de {self.MAX_IMAGES_PER_RESOURCE} images.'
            )


@receiver(post_delete, sender=ResourceImage)
def delete_resource_image_file(sender, instance, **kwargs):
    if instance.image and instance.image.name:
        instance.image.storage.delete(instance.image.name)


class Availability(TimeStampedModel):
    class Weekday(models.IntegerChoices):
        MONDAY = 0, 'Lundi'
        TUESDAY = 1, 'Mardi'
        WEDNESDAY = 2, 'Mercredi'
        THURSDAY = 3, 'Jeudi'
        FRIDAY = 4, 'Vendredi'
        SATURDAY = 5, 'Samedi'
        SUNDAY = 6, 'Dimanche'

    resource = models.ForeignKey(
        Resource,
        on_delete=models.CASCADE,
        related_name='availabilities',
    )
    weekday = models.PositiveSmallIntegerField(choices=Weekday.choices)
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['resource', 'weekday', 'start_time']
        indexes = [
            models.Index(fields=['resource', 'weekday', 'is_active']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_time__gt=models.F('start_time')),
                name='availability_end_after_start',
            ),
            models.UniqueConstraint(
                fields=['resource', 'weekday', 'start_time', 'end_time'],
                name='unique_resource_weekly_availability',
            ),
        ]
        verbose_name = 'disponibilité'
        verbose_name_plural = 'disponibilités'

    def __str__(self):
        return f'{self.resource} - {self.get_weekday_display()} {self.start_time}-{self.end_time}'


class UnavailablePeriod(TimeStampedModel):
    resource = models.ForeignKey(
        Resource,
        on_delete=models.CASCADE,
        related_name='unavailable_periods',
    )
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    reason = models.CharField(max_length=180, blank=True)

    class Meta:
        ordering = ['starts_at']
        indexes = [
            models.Index(fields=['resource', 'starts_at', 'ends_at']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F('starts_at')),
                name='unavailable_period_end_after_start',
            ),
        ]
        verbose_name = 'période indisponible'
        verbose_name_plural = 'périodes indisponibles'

    def __str__(self):
        return f'{self.resource} indisponible du {self.starts_at:%d/%m/%Y %H:%M}'

    def clean(self):
        errors = {}

        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            errors['ends_at'] = 'La date de fin doit être après la date de début.'

        if self.resource_id and self.starts_at and self.ends_at and self.ends_at > self.starts_at:
            overlap_query = UnavailablePeriod.objects.filter(
                resource=self.resource,
                starts_at__lt=self.ends_at,
                ends_at__gt=self.starts_at,
            )
            if self.pk:
                overlap_query = overlap_query.exclude(pk=self.pk)

            if overlap_query.exists():
                errors['starts_at'] = (
                    'Cette période chevauche déjà une autre indisponibilité de cette ressource.'
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class Reservation(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = 'pending', 'En attente'
        CONFIRMED = 'confirmed', 'Confirmée'
        CANCELLED = 'cancelled', 'Annulée'
        COMPLETED = 'completed', 'Terminée'

    BLOCKING_STATUSES = [Status.PENDING, Status.CONFIRMED]

    resource = models.ForeignKey(
        Resource,
        on_delete=models.PROTECT,
        related_name='reservations',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reservations',
    )
    customer_name = models.CharField(max_length=150)
    customer_email = models.EmailField()
    customer_phone = models.CharField(max_length=30, blank=True)
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField()
    attendees_count = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    total_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    notes = models.TextField(blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-start_datetime']
        indexes = [
            models.Index(fields=['resource', 'start_datetime', 'end_datetime']),
            models.Index(fields=['status']),
            models.Index(fields=['customer_email']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_datetime__gt=models.F('start_datetime')),
                name='reservation_end_after_start',
            ),
            models.CheckConstraint(
                condition=models.Q(attendees_count__gte=1),
                name='reservation_attendees_positive',
            ),
        ]
        verbose_name = 'réservation'
        verbose_name_plural = 'réservations'

    def __str__(self):
        return f'{self.resource} - {self.customer_name} ({self.start_datetime:%d/%m/%Y %H:%M})'

    @property
    def duration(self):
        if not self.start_datetime or not self.end_datetime:
            return None
        return self.end_datetime - self.start_datetime

    @property
    def billable_days(self):
        if not self.start_datetime or not self.end_datetime:
            return 0

        start_datetime = self._as_local_datetime(self.start_datetime)
        end_datetime = self._as_local_datetime(self.end_datetime)
        return (end_datetime.date() - start_datetime.date()).days + 1

    @property
    def is_paid(self):
        return self.payments.filter(status=Payment.Status.SUCCEEDED).exists()

    def calculate_total_amount(self):
        if not self.resource_id:
            return Decimal('0.00')
        return self.resource.price * max(self.billable_days, 1)

    def _as_local_datetime(self, value):
        if timezone.is_aware(value):
            return timezone.localtime(value)
        return value

    def clean(self):
        errors = {}

        if self.start_datetime and self.end_datetime:
            if self.end_datetime <= self.start_datetime:
                errors['end_datetime'] = 'La date de fin doit être après la date de début.'

        if self.resource_id and self.attendees_count and self.attendees_count > self.resource.capacity:
            errors['attendees_count'] = 'Le nombre de participants dépasse la capacité de la ressource.'

        if (
            self.resource_id
            and self.start_datetime
            and self.end_datetime
            and self.end_datetime > self.start_datetime
            and self.status in self.BLOCKING_STATUSES
        ):
            overlap_query = Reservation.objects.filter(
                resource=self.resource,
                status__in=self.BLOCKING_STATUSES,
                start_datetime__lt=self.end_datetime,
                end_datetime__gt=self.start_datetime,
            )
            if self.pk:
                overlap_query = overlap_query.exclude(pk=self.pk)

            if overlap_query.exists():
                errors['start_datetime'] = (
                    'Cette ressource est déjà occupée sur la période sélectionnée. '
                    'Nous ne pouvons pas la fournir sur ce créneau.'
                )

            unavailable_query = UnavailablePeriod.objects.filter(
                resource=self.resource,
                starts_at__lt=self.end_datetime,
                ends_at__gt=self.start_datetime,
            )

            if unavailable_query.exists() and 'start_datetime' not in errors:
                errors['start_datetime'] = (
                    'Cette ressource est indisponible sur la période sélectionnée. '
                    'Nous ne pouvons pas la louer sur ce créneau.'
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.status == self.Status.CANCELLED and self.cancelled_at is None:
            self.cancelled_at = timezone.now()
        if self.status != self.Status.CANCELLED:
            self.cancelled_at = None
        self.full_clean()
        super().save(*args, **kwargs)


class Payment(TimeStampedModel):
    class Method(models.TextChoices):
        CARD = 'card', 'Carte bancaire'
        MOBILE_MONEY = 'mobile_money', 'Mobile Money'
        CASH = 'cash', 'Espèces'
        OTHER = 'other', 'Autre'

    class Status(models.TextChoices):
        PENDING = 'pending', 'En attente'
        SUCCEEDED = 'succeeded', 'Réussi'
        FAILED = 'failed', 'Échoué'
        CANCELLED = 'cancelled', 'Annulé'
        REFUNDED = 'refunded', 'Remboursé'

    reservation = models.ForeignKey(
        Reservation,
        on_delete=models.CASCADE,
        related_name='payments',
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    currency = models.CharField(max_length=3, default='XOF')
    method = models.CharField(
        max_length=20,
        choices=Method.choices,
        default=Method.MOBILE_MONEY,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    provider = models.CharField(max_length=80, blank=True)
    provider_reference = models.CharField(max_length=150, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['provider_reference']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['provider', 'provider_reference'],
                condition=~models.Q(provider_reference=''),
                name='unique_non_empty_payment_reference',
            ),
        ]
        verbose_name = 'paiement'
        verbose_name_plural = 'paiements'

    def __str__(self):
        return f'{self.amount} {self.currency} - {self.get_status_display()}'

    def save(self, *args, **kwargs):
        if self.status == self.Status.SUCCEEDED and self.paid_at is None:
            self.paid_at = timezone.now()
        if self.status in [self.Status.PENDING, self.Status.FAILED, self.Status.CANCELLED]:
            self.paid_at = None
        self.full_clean()
        super().save(*args, **kwargs)
