from django.contrib import admin

from .models import (
    Availability,
    Payment,
    Reservation,
    Resource,
    ResourceCategory,
    UnavailablePeriod,
)


@admin.register(ResourceCategory)
class ResourceCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'description')
    prepopulated_fields = {'slug': ('name',)}


class AvailabilityInline(admin.TabularInline):
    model = Availability
    extra = 1


class UnavailablePeriodInline(admin.TabularInline):
    model = UnavailablePeriod
    extra = 0


@admin.register(Resource)
class ResourceAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'resource_type',
        'category',
        'capacity',
        'price',
        'requires_payment',
        'is_active',
    )
    list_filter = ('resource_type', 'category', 'requires_payment', 'is_active')
    search_fields = ('name', 'description', 'location')
    prepopulated_fields = {'slug': ('name',)}
    inlines = (AvailabilityInline, UnavailablePeriodInline)


@admin.register(Availability)
class AvailabilityAdmin(admin.ModelAdmin):
    list_display = ('resource', 'weekday', 'start_time', 'end_time', 'is_active')
    list_filter = ('weekday', 'is_active')
    search_fields = ('resource__name',)


@admin.register(UnavailablePeriod)
class UnavailablePeriodAdmin(admin.ModelAdmin):
    list_display = ('resource', 'starts_at', 'ends_at', 'reason')
    list_filter = ('starts_at',)
    search_fields = ('resource__name', 'reason')


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    readonly_fields = ('paid_at',)


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = (
        'resource',
        'customer_name',
        'customer_email',
        'start_datetime',
        'end_datetime',
        'attendees_count',
        'status',
        'total_amount',
    )
    list_filter = ('status', 'resource', 'start_datetime')
    search_fields = ('customer_name', 'customer_email', 'customer_phone', 'resource__name')
    readonly_fields = ('cancelled_at',)
    inlines = (PaymentInline,)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        'reservation',
        'amount',
        'currency',
        'method',
        'status',
        'provider',
        'provider_reference',
        'paid_at',
    )
    list_filter = ('status', 'method', 'currency')
    search_fields = ('provider_reference', 'reservation__customer_email', 'reservation__customer_name')
    readonly_fields = ('paid_at',)
