# -*- coding: utf-8 -*-
# Generated by Django 1.9.7 on 2016-09-28 07:49
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mixed', '0003_auto_20160928_1506'),
    ]

    operations = [
        migrations.AddField(
            model_name='document',
            name='is_deleted',
            field=models.BooleanField(db_column='isDeleted', default=False),
        ),
        migrations.AlterField(
            model_name='document',
            name='converter',
            field=models.CharField(blank=True, choices=[('N', 'Normal'), ('S', 'Server List')], default='N', max_length=1, null=True),
        ),
    ]
