"""
catalog/services/importer.py

Bulk import of Categories, Products, Variants and Images from an Excel (.xlsx) file.

Sheets (see catalog_import_template.xlsx):
    Categories | Products | Variants | Images

Behaviour
    * Upsert by SKU (product.sku / variant.sku) -> safe to re-import.
    * On UPDATE a blank cell means "leave as is"; on CREATE it means "use model default".
    * All-or-nothing: if any row fails, the DB transaction is rolled back and
      every error is reported with sheet name + Excel row number.
    * dry_run=True validates everything and rolls back at the end.
"""

import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from openpyxl import load_workbook

from catalog.models import Category, Product, ProductImage, ProductVariant

MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB
CATEGORY_SEP = ">"

PRODUCT_TEXT = [
    "name", "brand", "short_description", "description", "about_title",
    "about_heading", "ingredients_title", "ingredients", "usage",
]
PRODUCT_DECIMAL = ["base_price", "sale_price", "weight", "length_cm", "width_cm", "height_cm"]
PRODUCT_INT = ["stock_quantity"]
PRODUCT_LISTS = ["recommended_for", "good_to_know"]
PRODUCT_BOOL = ["is_featured", "is_active"]


# ---------------------------------------------------------------------------
# Result object
# ---------------------------------------------------------------------------

@dataclass
class ImportResult:
    created: dict = field(default_factory=lambda: {"categories": 0, "products": 0, "variants": 0, "images": 0})
    updated: dict = field(default_factory=lambda: {"categories": 0, "products": 0, "variants": 0, "images": 0})
    skipped: dict = field(default_factory=lambda: {"images": 0})
    errors: list = field(default_factory=list)
    dry_run: bool = False

    @property
    def ok(self):
        return not self.errors

    def as_dict(self):
        return {
            "ok": self.ok,
            "dry_run": self.dry_run,
            "created": self.created,
            "updated": self.updated,
            "skipped": self.skipped,
            "errors": self.errors,
        }


class RowError(Exception):
    """Raised for a problem with a single row; message is shown to the user."""


# ---------------------------------------------------------------------------
# Cell parsing helpers
# ---------------------------------------------------------------------------

def _text(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))          # SKU 123.0 -> "123"
    return str(v).strip()


def _decimal(v, label):
    s = _text(v)
    if s == "":
        return None
    try:
        return Decimal(s.replace(",", ""))
    except InvalidOperation:
        raise RowError(f"'{label}' must be a number, got '{s}'.")


def _int(v, label):
    d = _decimal(v, label)
    if d is None:
        return None
    if d != d.to_integral_value() or d < 0:
        raise RowError(f"'{label}' must be a whole number >= 0, got '{_text(v)}'.")
    return int(d)


def _bool(v, label):
    if isinstance(v, bool):
        return v
    s = _text(v).lower()
    if s == "":
        return None
    if s in ("true", "yes", "y", "1"):
        return True
    if s in ("false", "no", "n", "0"):
        return False
    raise RowError(f"'{label}' must be TRUE or FALSE, got '{_text(v)}'.")


def _pipe_list(v):
    s = _text(v)
    if not s:
        return None
    return [p.strip() for p in s.split("|") if p.strip()]


def _faqs(v):
    s = _text(v)
    if not s:
        return None
    out = []
    for chunk in s.split("||"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "::" not in chunk:
            raise RowError(f"FAQ '{chunk[:40]}...' must look like  Question::Answer")
        q, a = chunk.split("::", 1)
        out.append({"question": q.strip(), "answer": a.strip()})
    return out


def _attributes(v):
    s = _text(v)
    if not s:
        return None
    out = {}
    for pair in s.split(";"):
        pair = pair.strip()
        if not pair:
            continue
        if "=" not in pair:
            raise RowError(f"Attribute '{pair}' must look like  key=value")
        k, val = pair.split("=", 1)
        out[k.strip()] = val.strip()
    return out


def _format_validation_error(exc):
    if hasattr(exc, "message_dict"):
        return "; ".join(f"{k}: {' '.join(v)}" for k, v in exc.message_dict.items())
    return " ".join(exc.messages)


# ---------------------------------------------------------------------------
# Importer
# ---------------------------------------------------------------------------

class CatalogImporter:
    def __init__(self, file, dry_run=False):
        self.file = file
        self.dry_run = dry_run
        self.result = ImportResult(dry_run=dry_run)
        self._category_cache = {}

    # -- public -----------------------------------------------------------

    def run(self):
        try:
            wb = load_workbook(self.file, data_only=True)
        except Exception as exc:
            self.result.errors.append(f"Could not read the Excel file: {exc}")
            return self.result

        with transaction.atomic():
            self._import_categories(wb)
            self._import_products(wb)
            self._import_variants(wb)
            if self.result.ok:           # only touch files/network if all data rows are valid
                self._import_images(wb)
            if not self.result.ok or self.dry_run:
                transaction.set_rollback(True)
        return self.result

    # -- sheet reader -------------------------------------------------------

    def _rows(self, wb, name, required_headers=()):
        if name not in wb.sheetnames:
            return
        ws = wb[name]
        headers = [_text(c.value).lower() for c in ws[1]]
        missing = [h for h in required_headers if h not in headers]
        if missing:
            self.result.errors.append(f"[{name}] missing column(s): {', '.join(missing)}")
            return
        for idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            if all(_text(c) == "" for c in row):
                continue
            yield idx, {h: v for h, v in zip(headers, row) if h}

    def _err(self, sheet, row, msg):
        self.result.errors.append(f"[{sheet}] row {row}: {msg}")

    # -- categories ---------------------------------------------------------

    def _get_category(self, path, create=True):
        parts = [p.strip() for p in str(path).split(CATEGORY_SEP) if p.strip()]
        if not parts:
            raise RowError("category_path is empty.")
        parent, created_any, key = None, False, ()
        for name in parts:
            key += (name.lower(),)
            if key in self._category_cache:
                parent = self._category_cache[key]
                continue
            qs = Category.objects.filter(name__iexact=name, parent=parent)
            cat = qs.first()
            if cat is None:
                if not create:
                    raise RowError(f"Category '{path}' does not exist.")
                cat = Category.objects.create(name=name, parent=parent)
                self.result.created["categories"] += 1
                created_any = True
            self._category_cache[key] = cat
            parent = cat
        return parent, created_any

    def _import_categories(self, wb):
        for row, d in self._rows(wb, "Categories", ["category_path"]):
            try:
                with transaction.atomic():
                    cat, created = self._get_category(_text(d.get("category_path")))
                    changed = False
                    desc = _text(d.get("description"))
                    if desc:
                        cat.description, changed = desc, True
                    active = _bool(d.get("is_active"), "is_active")
                    if active is not None:
                        cat.is_active, changed = active, True
                    img = _text(d.get("image"))
                    if img and not self.dry_run:
                        name, content = self._fetch_image(img)
                        cat.image.save(name, content, save=False)
                        changed = True
                    if changed:
                        cat.save()
                        if not created:
                            self.result.updated["categories"] += 1
            except RowError as e:
                self._err("Categories", row, str(e))
            except ValidationError as e:
                self._err("Categories", row, _format_validation_error(e))

    # -- products -----------------------------------------------------------

    def _import_products(self, wb):
        for row, d in self._rows(wb, "Products", ["sku", "name", "category_path", "base_price"]):
            try:
                with transaction.atomic():
                    sku = _text(d.get("sku"))
                    if not sku:
                        raise RowError("sku is required.")
                    product = Product.objects.filter(sku=sku).first()
                    creating = product is None
                    if creating:
                        product = Product(sku=sku)

                    for f in PRODUCT_TEXT:
                        v = _text(d.get(f))
                        if v:
                            setattr(product, f, v)
                    for f in PRODUCT_DECIMAL:
                        v = _decimal(d.get(f), f)
                        if v is not None:
                            setattr(product, f, v)
                    for f in PRODUCT_INT:
                        v = _int(d.get(f), f)
                        if v is not None:
                            setattr(product, f, v)
                    for f in PRODUCT_LISTS:
                        v = _pipe_list(d.get(f))
                        if v is not None:
                            setattr(product, f, v)
                    faqs = _faqs(d.get("faqs"))
                    if faqs is not None:
                        product.faqs = faqs
                    for f in PRODUCT_BOOL:
                        v = _bool(d.get(f), f)
                        if v is not None:
                            setattr(product, f, v)

                    path = _text(d.get("category_path"))
                    if path:
                        product.category, _ = self._get_category(path)

                    if creating:
                        missing = [f for f in ("name", "base_price") if not getattr(product, f, None)]
                        if not getattr(product, "category_id", None):
                            missing.append("category_path")
                        if missing:
                            raise RowError(f"Required for new products: {', '.join(missing)}.")

                    product.save()   # model.save() runs full_clean()
                    (self.result.created if creating else self.result.updated)["products"] += 1
            except RowError as e:
                self._err("Products", row, str(e))
            except ValidationError as e:
                self._err("Products", row, _format_validation_error(e))

    # -- variants -----------------------------------------------------------

    def _import_variants(self, wb):
        for row, d in self._rows(wb, "Variants", ["product_sku", "variant_sku", "name", "price"]):
            try:
                with transaction.atomic():
                    psku, vsku = _text(d.get("product_sku")), _text(d.get("variant_sku"))
                    if not psku or not vsku:
                        raise RowError("product_sku and variant_sku are required.")
                    product = Product.objects.filter(sku=psku).first()
                    if product is None:
                        raise RowError(f"Product with sku '{psku}' not found.")

                    variant = ProductVariant.objects.filter(sku=vsku).first()
                    creating = variant is None
                    if creating:
                        variant = ProductVariant(sku=vsku, product=product)
                    elif variant.product_id != product.id:
                        raise RowError(f"Variant sku '{vsku}' already belongs to another product.")

                    name = _text(d.get("name"))
                    if name:
                        variant.name = name
                    for f in ("price", "sale_price", "weight"):
                        v = _decimal(d.get(f), f)
                        if v is not None:
                            setattr(variant, f, v)
                    stock = _int(d.get("stock_quantity"), "stock_quantity")
                    if stock is not None:
                        variant.stock_quantity = stock
                    attrs = _attributes(d.get("attributes"))
                    if attrs is not None:
                        variant.attributes = attrs
                    for f in ("is_default", "is_active"):
                        v = _bool(d.get(f), f)
                        if v is not None:
                            setattr(variant, f, v)

                    if creating and (not variant.name or getattr(variant, "price", None) is None):
                        raise RowError("name and price are required for new variants.")

                    variant.save()
                    (self.result.created if creating else self.result.updated)["variants"] += 1
            except RowError as e:
                self._err("Variants", row, str(e))
            except ValidationError as e:
                self._err("Variants", row, _format_validation_error(e))

    # -- images -------------------------------------------------------------

    def _fetch_image(self, source):
        """Return (filename, ContentFile) from an http(s) URL or a local path."""
        parsed = urlparse(source)
        if parsed.scheme in ("http", "https"):
            req = Request(source, headers={"User-Agent": "catalog-importer/1.0"})
            try:
                with urlopen(req, timeout=20) as resp:
                    data = resp.read(MAX_IMAGE_BYTES + 1)
            except Exception as exc:
                raise RowError(f"Could not download image '{source}': {exc}")
            filename = parsed.path.rsplit("/", 1)[-1]
        else:
            try:
                with open(source, "rb") as fh:
                    data = fh.read(MAX_IMAGE_BYTES + 1)
            except OSError as exc:
                raise RowError(f"Could not read image file '{source}': {exc}")
            filename = source.replace("\\", "/").rsplit("/", 1)[-1]
        if len(data) > MAX_IMAGE_BYTES:
            raise RowError(f"Image '{source}' is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB.")
        if not data:
            raise RowError(f"Image '{source}' is empty.")
        if "." not in filename:
            filename = f"{uuid.uuid4().hex}.jpg"
        return filename, ContentFile(data)

    def _import_images(self, wb):
        for row, d in self._rows(wb, "Images", ["image"]):
            try:
                with transaction.atomic():
                    psku, vsku = _text(d.get("product_sku")), _text(d.get("variant_sku"))
                    source = _text(d.get("image"))
                    if not source:
                        raise RowError("image is required.")
                    variant = product = None
                    if vsku:
                        variant = ProductVariant.objects.filter(sku=vsku).first()
                        if variant is None:
                            raise RowError(f"Variant with sku '{vsku}' not found.")
                    elif psku:
                        product = Product.objects.filter(sku=psku).first()
                        if product is None:
                            raise RowError(f"Product with sku '{psku}' not found.")
                    else:
                        raise RowError("Provide product_sku or variant_sku.")

                    filename, content = self._fetch_image(source)

                    # Skip if the same file name was already imported for this owner
                    stem = filename.rsplit(".", 1)[0]
                    existing = (variant.images if variant else product.images).filter(image__contains=stem)
                    if existing.exists():
                        self.result.skipped["images"] += 1
                        continue

                    img = ProductImage(
                        product=product, variant=variant,
                        alt_text=_text(d.get("alt_text")),
                        sort_order=_int(d.get("sort_order"), "sort_order") or 0,
                    )
                    img.image.save(filename, content, save=False)
                    img.save()
                    self.result.created["images"] += 1
            except RowError as e:
                self._err("Images", row, str(e))
            except ValidationError as e:
                self._err("Images", row, _format_validation_error(e))