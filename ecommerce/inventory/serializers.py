"""inventory/serializers.py"""

from rest_framework import serializers

from catalog.models import Product, ProductVariant

from .models import PurchaseOrder, PurchaseOrderItem, StockMovement, StockPolicy, Supplier

M = StockMovement.Type

# Types a person may pick by hand. SALE / ORDER_CANCEL / EXTERNAL / INITIAL are system-written.
MANUAL_TYPES = [M.ADJUSTMENT, M.DAMAGE, M.RETURN, M.PURCHASE_RECEIPT, M.STOCKTAKE]


class TargetMixin(serializers.Serializer):
    """Exactly one of product_id / variant_id."""
    product_id = serializers.UUIDField(required=False)
    variant_id = serializers.UUIDField(required=False)

    def validate(self, attrs):
        if bool(attrs.get("product_id")) == bool(attrs.get("variant_id")):
            raise serializers.ValidationError("Provide exactly one of product_id or variant_id.")
        return attrs


class AdjustSerializer(TargetMixin):
    change = serializers.IntegerField(help_text="Positive adds stock, negative removes it.")
    movement_type = serializers.ChoiceField(choices=MANUAL_TYPES, default=M.ADJUSTMENT)
    reference = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")

    def validate_change(self, v):
        if v == 0:
            raise serializers.ValidationError("change must not be zero.")
        return v


class SetStockSerializer(TargetMixin):
    quantity = serializers.IntegerField(min_value=0)
    reference = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class BulkAdjustSerializer(serializers.Serializer):
    items = AdjustSerializer(many=True, allow_empty=False, max_length=500)


class StockMovementSerializer(serializers.ModelSerializer):
    created_by_email = serializers.EmailField(source="created_by.email", read_only=True, default=None)
    movement_type_display = serializers.CharField(source="get_movement_type_display", read_only=True)

    class Meta:
        model = StockMovement
        fields = [
            "id", "product", "variant", "sku", "item_name",
            "movement_type", "movement_type_display",
            "quantity_change", "quantity_before", "quantity_after",
            "reference", "note", "created_by", "created_by_email", "created_at",
        ]
        read_only_fields = fields


class StockPolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = StockPolicy
        fields = ["id", "product", "variant", "low_stock_threshold",
                  "reorder_quantity", "preferred_supplier"]

    def validate(self, attrs):
        product = attrs.get("product", getattr(self.instance, "product", None))
        variant = attrs.get("variant", getattr(self.instance, "variant", None))
        if bool(product) == bool(variant):
            raise serializers.ValidationError("Provide exactly one of product or variant.")
        if product and product.variants.exists():
            raise serializers.ValidationError(
                {"product": "This product has variants – set the policy on each variant."})
        return attrs


class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = ["id", "name", "contact_name", "email", "phone", "address",
                  "lead_time_days", "is_active", "created_at", "updated_at"]
        read_only_fields = ["id", "created_at", "updated_at"]


class PurchaseOrderItemSerializer(serializers.ModelSerializer):
    quantity_outstanding = serializers.IntegerField(read_only=True)
    product_id = serializers.PrimaryKeyRelatedField(
        queryset=Product.objects.all(), source="product", required=False, write_only=True)
    variant_id = serializers.PrimaryKeyRelatedField(
        queryset=ProductVariant.objects.select_related("product"), source="variant",
        required=False, write_only=True)

    class Meta:
        model = PurchaseOrderItem
        fields = ["id", "product_id", "variant_id", "sku", "item_name", "quantity_ordered",
                  "quantity_received", "quantity_outstanding", "unit_cost"]
        read_only_fields = ["id", "sku", "item_name", "quantity_received"]

    def validate(self, attrs):
        product, variant = attrs.get("product"), attrs.get("variant")
        if bool(product) == bool(variant):
            raise serializers.ValidationError("Provide exactly one of product_id or variant_id.")
        if product and product.variants.exists():
            raise serializers.ValidationError("This product has variants – order a specific variant.")
        if attrs["quantity_ordered"] < 1:
            raise serializers.ValidationError({"quantity_ordered": "Must be at least 1."})
        if variant:
            attrs["sku"], attrs["item_name"] = variant.sku, f"{variant.product.name} – {variant.name}"
        else:
            attrs["sku"], attrs["item_name"] = product.sku, product.name
        return attrs


class PurchaseOrderSerializer(serializers.ModelSerializer):
    items = PurchaseOrderItemSerializer(many=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    total_cost = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)

    class Meta:
        model = PurchaseOrder
        fields = ["id", "po_number", "supplier", "supplier_name", "status", "expected_date",
                  "notes", "items", "total_cost", "ordered_at", "received_at",
                  "created_at", "updated_at"]
        read_only_fields = ["id", "po_number", "status", "ordered_at", "received_at",
                            "created_at", "updated_at"]

    def validate_supplier(self, s):
        if not s.is_active:
            raise serializers.ValidationError("Supplier is inactive.")
        return s

    def validate_items(self, items):
        if not items:
            raise serializers.ValidationError("A purchase order needs at least one line.")
        return items

    def create(self, validated):
        items = validated.pop("items")
        po = PurchaseOrder.objects.create(created_by=self.context["request"].user, **validated)
        PurchaseOrderItem.objects.bulk_create([PurchaseOrderItem(purchase_order=po, **i) for i in items])
        return po

    def update(self, instance, validated):
        # Only drafts are editable; lines are replaced wholesale.
        if instance.status != PurchaseOrder.Status.DRAFT:
            raise serializers.ValidationError("Only draft purchase orders can be edited.")
        items = validated.pop("items", None)
        for k, v in validated.items():
            setattr(instance, k, v)
        instance.save()
        if items is not None:
            instance.items.all().delete()
            PurchaseOrderItem.objects.bulk_create([PurchaseOrderItem(purchase_order=instance, **i) for i in items])
        return instance


class ReceiveLineSerializer(serializers.Serializer):
    item_id = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1)


class ReceiveSerializer(serializers.Serializer):
    # Omit "lines" to receive everything outstanding.
    lines = ReceiveLineSerializer(many=True, required=False, allow_empty=False)
