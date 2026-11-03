import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('main', '0017_album_similars'),
    ]

    # similar artists are fetched per artist instead of per album, so the old rows go
    operations = [
        migrations.DeleteModel(
            name='Similar',
        ),
        migrations.RemoveField(
            model_name='album',
            name='similars_at',
        ),
        migrations.AddField(
            model_name='artist',
            name='similars_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name='Similar',
            fields=[
                (
                    'id',
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name='ID'
                    ),
                ),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('artist_name', models.CharField(max_length=250)),
                ('artist_slug', models.SlugField(max_length=250)),
                ('match', models.FloatField()),
                ('rating', models.FloatField()),
                ('score', models.FloatField()),
                ('scraped_at', models.DateTimeField()),
                (
                    'artist',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='similars',
                        to='main.artist',
                    ),
                ),
            ],
            options={
                'unique_together': {('artist', 'artist_slug')},
            },
        ),
    ]
