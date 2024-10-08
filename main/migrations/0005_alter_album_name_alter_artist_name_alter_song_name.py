# Generated by Django 5.1.1 on 2024-09-18 14:41

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('main', '0004_alter_album_name'),
    ]

    operations = [
        migrations.AlterField(
            model_name='album',
            name='name',
            field=models.CharField(max_length=150),
        ),
        migrations.AlterField(
            model_name='artist',
            name='name',
            field=models.CharField(max_length=150, unique=True),
        ),
        migrations.AlterField(
            model_name='song',
            name='name',
            field=models.CharField(max_length=150),
        ),
    ]
