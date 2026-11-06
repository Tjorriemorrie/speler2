from django.db import migrations
from django.utils import timezone


def clear_future_disco_at(apps, schema_editor):
    """Reviewing used to date artists in the future, ahead of the back of the queue."""
    artist_model = apps.get_model('main', 'Artist')
    artist_model.objects.filter(disco_at__gt=timezone.now()).update(disco_at=timezone.now())


class Migration(migrations.Migration):
    dependencies = [
        ('main', '0018_artist_similars'),
    ]

    operations = [
        migrations.RunPython(clear_future_disco_at, migrations.RunPython.noop),
    ]
