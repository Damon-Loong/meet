from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0027_account_contact"),
    ]

    operations = [
        migrations.AddField(
            model_name="room",
            name="is_permanent",
            field=models.BooleanField(
                default=False,
                help_text="仅即时会议适用；空闲时链接不会自动失效。",
                verbose_name="长期有效链接",
            ),
        ),
    ]
