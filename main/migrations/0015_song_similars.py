# Similars move from artists to songs: the artist rows cannot be converted, so the table is recreated

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('main', '0014_alter_history_options_album_is_dirty_artist_is_dirty_and_more'),
    ]

    operations = [
        migrations.DeleteModel(
            name='Similar',
        ),
        migrations.AddField(
            model_name='song',
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
                ('track_name', models.CharField(max_length=250)),
                ('track_slug', models.SlugField(max_length=250)),
                ('match', models.FloatField()),
                ('rating', models.FloatField()),
                ('score', models.FloatField()),
                ('scraped_at', models.DateTimeField()),
                (
                    'song',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='similars',
                        to='main.song',
                    ),
                ),
            ],
            options={
                'unique_together': {('song', 'artist_slug', 'track_slug')},
            },
        ),
    ]
