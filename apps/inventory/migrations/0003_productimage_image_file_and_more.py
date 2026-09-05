from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("inventory", "0002_productimage_alter_stockbalance_unique_together_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="productimage",
            name="image_url",
            field=models.URLField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name="productimage",
            name="image_file",
            field=models.ImageField(
                blank=True,
                null=True,
                upload_to="product-images/%Y/%m/%d/",
            ),
        ),
    ]
