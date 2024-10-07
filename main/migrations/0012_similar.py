# Generated by Django 5.1.1 on 2024-09-27 06:09

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('main', '0011_alter_billboard_options_billboard_finished_and_more'),
    ]

    operations = [
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
