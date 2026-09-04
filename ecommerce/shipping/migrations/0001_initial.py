import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('orders', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Shipment',
            fields=[
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('shiprocket_order_id', models.CharField(blank=True, db_index=True, max_length=64)),
                ('shiprocket_shipment_id', models.CharField(blank=True, db_index=True, max_length=64)),
                ('awb_code', models.CharField(blank=True, db_index=True, max_length=64)),
                ('courier_id', models.CharField(blank=True, max_length=32)),
                ('courier_name', models.CharField(blank=True, max_length=200)),
                ('tracking_url', models.URLField(blank=True, max_length=500)),
                ('label_url', models.URLField(blank=True, max_length=500)),
                ('manifest_url', models.URLField(blank=True, max_length=500)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('created', 'Created'), ('awb_assigned', 'AWB Assigned'), ('picked_up', 'Picked Up'), ('in_transit', 'In Transit'), ('out_for_delivery', 'Out for Delivery'), ('delivered', 'Delivered'), ('rto', 'Return to Origin'), ('cancelled', 'Cancelled'), ('failed', 'Failed')], db_index=True, default='pending', max_length=20)),
                ('pickup_location', models.CharField(blank=True, max_length=100)),
                ('package_weight_kg', models.DecimalField(blank=True, decimal_places=3, max_digits=8, null=True)),
                ('package_length_cm', models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ('package_width_cm', models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ('package_height_cm', models.DecimalField(blank=True, decimal_places=2, max_digits=8, null=True)),
                ('raw_create_response', models.JSONField(blank=True, default=dict)),
                ('raw_tracking_response', models.JSONField(blank=True, default=dict)),
                ('cancelled_at', models.DateTimeField(blank=True, null=True)),
                ('delivered_at', models.DateTimeField(blank=True, null=True)),
                ('order', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='shipment', to='orders.order')),
            ],
            options={
                'verbose_name': 'Shipment',
                'verbose_name_plural': 'Shipments',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='ShiprocketWebhookEvent',
            fields=[
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('dedup_key', models.CharField(db_index=True, max_length=64, unique=True)),
                ('awb_code', models.CharField(blank=True, db_index=True, max_length=64)),
                ('shiprocket_order_id', models.CharField(blank=True, db_index=True, max_length=64)),
                ('current_status', models.CharField(blank=True, max_length=100)),
                ('payload', models.JSONField(default=dict)),
                ('is_processed', models.BooleanField(default=False)),
                ('processed_at', models.DateTimeField(blank=True, null=True)),
                ('processing_error', models.CharField(blank=True, max_length=500)),
                ('shipment', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='webhook_events', to='shipping.shipment')),
            ],
            options={
                'verbose_name': 'Shiprocket Webhook Event',
                'verbose_name_plural': 'Shiprocket Webhook Events',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='shipment',
            index=models.Index(fields=['status'], name='shipping_sh_status_0644c6_idx'),
        ),
        migrations.AddIndex(
            model_name='shipment',
            index=models.Index(fields=['awb_code'], name='shipping_sh_awb_cod_6606a7_idx'),
        ),
        migrations.AddIndex(
            model_name='shipment',
            index=models.Index(fields=['shiprocket_order_id'], name='shipping_sh_shiproc_468708_idx'),
        ),
        migrations.AddIndex(
            model_name='shiprocketwebhookevent',
            index=models.Index(fields=['awb_code'], name='shipping_sh_awb_cod_0dd09d_idx'),
        ),
    ]
