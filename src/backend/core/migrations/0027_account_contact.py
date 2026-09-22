# Generated manually for account-scoped historical meeting contacts.

import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0026_localize_scheduling_admin"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AccountContact",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        help_text="primary key for the record as UUID",
                        primary_key=True,
                        serialize=False,
                        verbose_name="id",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        help_text="date and time at which a record was created",
                        verbose_name="created on",
                    ),
                ),
                (
                    "updated_at",
                    models.DateTimeField(
                        auto_now=True,
                        help_text="date and time at which a record was last updated",
                        verbose_name="updated on",
                    ),
                ),
                ("name", models.CharField(max_length=255, verbose_name="姓名")),
                ("email", models.EmailField(max_length=254, verbose_name="邮箱")),
                (
                    "linked_user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="contact_entries",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="关联登录账号",
                    ),
                ),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="meeting_contacts",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="所属账号",
                    ),
                ),
            ],
            options={
                "verbose_name": "账号联系人",
                "verbose_name_plural": "账号联系人",
                "db_table": "meet_account_contact",
                "ordering": ("-updated_at",),
                "indexes": [
                    models.Index(
                        fields=["owner", "email"],
                        name="acct_contact_owner_email_idx",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("owner", "email"), name="uniq_account_contact_email"
                    )
                ],
            },
        )
    ]
