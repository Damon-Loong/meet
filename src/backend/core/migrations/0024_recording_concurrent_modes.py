from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0023_room_topic")]

    operations = [
        migrations.RemoveConstraint(
            model_name="recording",
            name="unique_initiated_or_active_recording_per_room",
        ),
        migrations.AddConstraint(
            model_name="recording",
            constraint=models.UniqueConstraint(
                condition=models.Q(status__in=["active", "initiated"]),
                fields=("room", "mode"),
                name="unique_active_recording_per_room_and_mode",
            ),
        ),
    ]
