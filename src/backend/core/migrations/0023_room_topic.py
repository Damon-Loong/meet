from django.db import migrations, models


def populate_room_topics(apps, schema_editor):
    Room = apps.get_model("core", "Room")
    for room in Room.objects.filter(topic="").iterator():
        room.topic = room.name
        room.save(update_fields=["topic"])


class Migration(migrations.Migration):
    dependencies = [("core", "0022_user_default_room_access_level_and_more")]

    operations = [
        migrations.AddField(
            model_name="room",
            name="topic",
            field=models.CharField(
                blank=True,
                default="",
                max_length=500,
                verbose_name="Meeting subject",
            ),
        ),
        migrations.RunPython(populate_room_topics, migrations.RunPython.noop),
    ]
