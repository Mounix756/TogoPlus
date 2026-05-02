from django import forms

from .models import Reservation, Resource, ResourceCategory, ResourceImage, UnavailablePeriod


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
            "resource_type",
            "description",
            "location",
            "capacity",
            "price",
            "requires_payment",
        ]

        labels = {
            "category": "Catégorie",
            "name": "Nom",
            "resource_type": "Type",
            "description": "Description",
            "location": "Lieu",
            "capacity": "Capacité",
            "price": "Prix",
            "requires_payment": "Paiement requis",
        }

        widgets = {
            "name": forms.TextInput(
                attrs={
                    "placeholder": "Nom de la salle, du service ou de l’équipement",
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

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.apply_form_styles()

    def save(self, commit=True):
        resource = super().save(commit=False)

        if resource.pk is None:
            resource.is_active = True
        if self.user is not None and self.user.is_authenticated:
            resource.manager = self.user

        if commit:
            resource.save()

        return resource


class ResourceCategoryForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ResourceCategory
        fields = [
            "name",
            "description",
            "is_active",
        ]

        labels = {
            "name": "Nom",
            "description": "Description",
            "is_active": "Catégorie active",
        }

        widgets = {
            "name": forms.TextInput(
                attrs={
                    "placeholder": "Nom de la catégorie",
                }
            ),
            "description": forms.Textarea(
                attrs={
                    "rows": 5,
                    "placeholder": "Décrivez le type de ressources regroupées dans cette catégorie.",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.apply_form_styles()


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleImageField(forms.ImageField):
    widget = MultipleFileInput

    def clean(self, data, initial=None):
        if not data:
            return []

        files = data if isinstance(data, (list, tuple)) else [data]
        return [super(MultipleImageField, self).clean(file, initial) for file in files]


class ResourceImagesUploadForm(forms.Form):
    images = MultipleImageField(
        label="Images",
        required=False,
        widget=MultipleFileInput(
            attrs={
                "accept": "image/*",
                "class": "form-control",
                "id": "resource-images-input",
                "multiple": True,
            }
        ),
        error_messages={
            "invalid_image": "Sélectionnez uniquement des images valides.",
        },
    )

    def __init__(self, *args, current_image_ids=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_image_ids = {int(pk) for pk in current_image_ids or []}
        self.cleaned_delete_image_ids = set()

    def clean(self):
        cleaned_data = super().clean()
        uploaded_images = cleaned_data.get("images") or []
        delete_image_ids = self._get_valid_delete_image_ids()
        remaining_count = len(self.current_image_ids) - len(delete_image_ids)

        if remaining_count + len(uploaded_images) > ResourceImage.MAX_IMAGES_PER_RESOURCE:
            raise forms.ValidationError(
                f"Une ressource ne peut pas contenir plus de {ResourceImage.MAX_IMAGES_PER_RESOURCE} images."
            )

        self.cleaned_delete_image_ids = delete_image_ids
        return cleaned_data

    def _get_valid_delete_image_ids(self):
        selected_ids = set()
        if hasattr(self.data, "getlist"):
            values = self.data.getlist("delete_images")
        else:
            values = self.data.get("delete_images", [])
            if isinstance(values, str):
                values = [values]

        for value in values:
            try:
                image_id = int(value)
            except (TypeError, ValueError):
                continue
            if image_id in self.current_image_ids:
                selected_ids.add(image_id)
        return selected_ids


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


class UnavailablePeriodForm(StyledFormMixin, forms.ModelForm):
    starts_at = forms.DateTimeField(
        label="Début",
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M",
            attrs={
                "type": "datetime-local",
            },
        ),
    )

    ends_at = forms.DateTimeField(
        label="Fin",
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(
            format="%Y-%m-%dT%H:%M",
            attrs={
                "type": "datetime-local",
            },
        ),
    )

    class Meta:
        model = UnavailablePeriod
        fields = [
            "resource",
            "starts_at",
            "ends_at",
            "reason",
        ]

        labels = {
            "resource": "Ressource",
            "reason": "Motif",
        }

        widgets = {
            "reason": forms.TextInput(
                attrs={
                    "placeholder": "Maintenance, événement privé, indisponibilité technique...",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["resource"].queryset = Resource.objects.order_by("name")
        self.apply_form_styles()
