from django import forms

from .models import Reservation, Resource


class StyledFormMixin:
    def apply_form_styles(self):
        for field_name, field in self.fields.items():
            widget = field.widget
            existing_classes = widget.attrs.get("class", "")

            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = f"{existing_classes} form-check-input".strip()
            else:
                widget.attrs["class"] = f"{existing_classes} form-control".strip()

            if isinstance(widget, forms.Select):
                widget.attrs["class"] = f"{existing_classes} form-control".strip()


class ReservationForm(StyledFormMixin, forms.ModelForm):
    start_datetime = forms.DateTimeField(
        label="Début",
        help_text="Choisissez la date et l’heure de début de votre réservation.",
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M",
            attrs={
                "type": "datetime-local",
                "id": "arrival_date",
            },
        ),
    )

    end_datetime = forms.DateTimeField(
        label="Fin",
        help_text="La date de fin peut être sur un autre jour pour une réservation multi-jours.",
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M",
            attrs={
                "type": "datetime-local",
                "id": "departure_date",
            },
        ),
    )

    class Meta:
        model = Reservation
        fields = [
            "customer_name",
            "customer_email",
            "customer_phone",
            "start_datetime",
            "end_datetime",
            "attendees_count",
            "notes",
        ]

        labels = {
            "customer_name": "Nom complet",
            "customer_email": "Email",
            "customer_phone": "Téléphone",
            "attendees_count": "Participants",
            "notes": "Message",
        }

        widgets = {
            "customer_name": forms.TextInput(
                attrs={
                    "placeholder": "Votre nom complet",
                }
            ),
            "customer_email": forms.EmailInput(
                attrs={
                    "placeholder": "exemple@email.com",
                }
            ),
            "customer_phone": forms.TextInput(
                attrs={
                    "placeholder": "+228 00 00 00 00",
                }
            ),
            "attendees_count": forms.NumberInput(
                attrs={
                    "min": 1,
                    "placeholder": "Nombre de participants",
                }
            ),
            "notes": forms.Textarea(
                attrs={
                    "rows": 8,
                    "placeholder": "Ajoutez une précision sur votre réservation, votre événement ou vos besoins particuliers.",
                }
            ),
        }

    def __init__(self, *args, resource=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.resource = resource
        self.user = user

        if self.resource is not None:
            self.instance.resource = self.resource
            self.instance.total_amount = self.resource.price

        self.apply_form_styles()

    def save(self, commit=True):
        reservation = super().save(commit=False)

        if self.resource is not None:
            reservation.resource = self.resource
            reservation.total_amount = reservation.calculate_total_amount()

        if self.user is not None and self.user.is_authenticated:
            reservation.user = self.user

        if commit:
            reservation.save()

        return reservation


class ResourceForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Resource
        fields = [
            "category",
            "name",
            "slug",
            "resource_type",
            "description",
            "location",
            "capacity",
            "price",
            "requires_payment",
            "is_active",
            "manager",
        ]

        labels = {
            "category": "Catégorie",
            "name": "Nom",
            "slug": "Slug",
            "resource_type": "Type",
            "description": "Description",
            "location": "Lieu",
            "capacity": "Capacité",
            "price": "Prix",
            "requires_payment": "Paiement requis",
            "is_active": "Active",
            "manager": "Gestionnaire",
        }

        widgets = {
            "name": forms.TextInput(
                attrs={
                    "placeholder": "Nom de la salle, du service ou de l’équipement",
                }
            ),
            "slug": forms.TextInput(
                attrs={
                    "placeholder": "exemple-salle-conference",
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "rows": 5,
                    "placeholder": "Décrivez la ressource, ses avantages et ses conditions d’utilisation.",
                }
            ),
            "location": forms.TextInput(
                attrs={
                    "placeholder": "Lieu ou adresse",
                }
            ),
            "capacity": forms.NumberInput(
                attrs={
                    "min": 1,
                    "placeholder": "Capacité maximale",
                }
            ),
            "price": forms.NumberInput(
                attrs={
                    "min": 0,
                    "placeholder": "Prix de base",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_form_styles()


class ReservationBackofficeForm(StyledFormMixin, forms.ModelForm):
    start_datetime = forms.DateTimeField(
        label="Début",
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M",
            attrs={
                "type": "datetime-local",
                "id": "arrival_date",
            },
        ),
    )

    end_datetime = forms.DateTimeField(
        label="Fin",
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M",
            attrs={
                "type": "datetime-local",
                "id": "departure_date",
            },
        ),
    )

    class Meta:
        model = Reservation
        fields = [
            "resource",
            "customer_name",
            "customer_email",
            "customer_phone",
            "start_datetime",
            "end_datetime",
            "attendees_count",
            "status",
            "total_amount",
            "notes",
        ]

        labels = {
            "resource": "Ressource",
            "customer_name": "Client",
            "customer_email": "Email",
            "customer_phone": "Téléphone",
            "attendees_count": "Participants",
            "status": "Statut",
            "total_amount": "Montant",
            "notes": "Notes",
        }

        widgets = {
            "customer_name": forms.TextInput(
                attrs={
                    "placeholder": "Nom du client",
                }
            ),
            "customer_email": forms.EmailInput(
                attrs={
                    "placeholder": "client@email.com",
                }
            ),
            "customer_phone": forms.TextInput(
                attrs={
                    "placeholder": "+228 00 00 00 00",
                }
            ),
            "attendees_count": forms.NumberInput(
                attrs={
                    "min": 1,
                }
            ),
            "total_amount": forms.NumberInput(
                attrs={
                    "min": 0,
                }
            ),
            "notes": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "Notes internes ou informations complémentaires.",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_form_styles()