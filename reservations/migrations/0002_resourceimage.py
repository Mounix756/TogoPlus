import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reservations', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='ResourceImage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('image', models.ImageField(upload_to='resources/')),
                ('sort_order', models.PositiveSmallIntegerField(default=0)),
                ('resource', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='images', to='reservations.resource')),
            ],
            options={
                'verbose_name': 'image de ressource',
                'verbose_name_plural': 'images de ressource',
                'ordering': ['sort_order', 'id'],
                'indexes': [models.Index(fields=['resource', 'sort_order'], name='reservation_resource_c4d687_idx')],
            },
        ),
    ]
