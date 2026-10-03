# inventory – stock management for the e-commerce project

Stock keeps living where your cart/checkout/orders/dashboard already read it
(`ProductVariant.stock_quantity`, or `Product.stock_quantity` for products
without variants). This app adds the management layer around it:

| Piece | What it does |
|---|---|
| **StockMovement** | Append-only ledger: every change with before/after, reason, reference (order / PO no.), user, time |
| **StockPolicy** | Per-item low-stock threshold, suggested reorder qty, preferred supplier |
| **Supplier / PurchaseOrder** | Order restock, receive deliveries (full or partial) – receiving writes ledger rows |
| **Stock API** | Levels + low/out filters, summary, adjust, bulk-adjust, stocktake, Excel export/import |
| **Signal safety net** | Edits made via Django admin / catalog API / Excel catalog importer are still logged (`external`) |

## Install (4 steps)

1. Copy the `inventory/` folder next to `catalog/`, `orders/`, etc.
2. Apply `integration.patch` (settings + urls + orders hook):
   `git apply integration.patch`  (or make the three small edits by hand – see patch)
3. `python manage.py migrate inventory`
4. `python manage.py test inventory`

Needs Django ≥ 5.1 (uses `CheckConstraint(condition=…)`); bump `requirements.txt` to `Django>=5.1,<6.0`.

Existing stock is not back-filled into the ledger. Items start with no history; the first
change creates the first row. (Optional one-off: run `set_stock` per item to write an opening row.)

## Endpoints  (`/api/admin/inventory/…`, JWT, response envelope `{status, data}`)

| Method | Path | Who | Notes |
|---|---|---|---|
| GET | `stock/` | staff+ | `?status=in_stock\|low\|out\|attention&q=&category=<slug>&kind=variant\|product` |
| GET | `stock/summary/` | staff+ | units on hand, value at selling price, in/low/out counts |
| POST | `stock/adjust/` | staff+ | `{variant_id｜product_id, change, movement_type, reference, note}` |
| POST | `stock/bulk-adjust/` | staff+ | `{items:[…same…]}` all-or-nothing |
| POST | `stock/set/` | manager+ | `{variant_id｜product_id, quantity, note}` absolute count |
| GET | `stock/export/` | staff+ | `.xlsx` of current (filtered) levels |
| POST | `stock/import/?dry_run=true` | manager+ | multipart `file=<xlsx>`; all-or-nothing |
| GET | `movements/` | staff+ | `?sku=&variant=&product=&type=&reference=&date_from=&date_to=` |
| CRUD | `policies/`, `suppliers/` | read staff+, write manager+ | suppliers with history are deactivated, not deleted |
| CRUD | `purchase-orders/` (+ `<id>/`) | read staff+, write manager+ | only drafts are editable |
| POST | `purchase-orders/<id>/mark-ordered/` · `cancel/` | manager+ | |
| POST | `purchase-orders/<id>/receive/` | staff+ | `{lines:[{item_id, quantity}]}`; omit `lines` to receive everything outstanding |

`movement_type` for manual changes: `adjustment`, `damage`, `return`, `purchase_receipt`, `stocktake`.
`sale`, `order_cancel`, `initial`, `external` are written by the system.

## Excel stocktake format

Columns (case-insensitive): **SKU**, **Counted quantity** (or `On hand` / `Quantity`), optional **Note**.
Variant SKUs and variant-less product SKUs both work. Download `stock/export/`, edit *On hand*, upload it back.
Any bad row (unknown SKU, negative/fractional qty, duplicate SKU, parent product that has variants) rejects the
whole file and nothing is changed. Use `?dry_run=true` to preview `from → to`.

## Housekeeping

`python manage.py low_stock_report [--out-only] [--csv]` – cron-friendly list of items to reorder.

Settings (optional): `INVENTORY_DEFAULT_LOW_STOCK_THRESHOLD = 10`, `INVENTORY_LOG_EXTERNAL_CHANGES = True`.

## Things to know

* **Always change stock through `inventory.services`** (`record_movement`, `set_stock`). A plain
  `obj.stock_quantity = …; obj.save()` still works and is logged as `external`, but it has no reason/user
  and, if the in-memory object is stale, can overwrite a newer quantity.
* `dashboard.get_inventory_report` still uses its own fixed threshold; it doesn't read `StockPolicy`.
* The stock list is built in Python and paginated in memory – fine for thousands of SKUs; move to a DB
  query if you reach hundreds of thousands.
* Stock is a single pool (no warehouses/locations, no reservations, no backorders, no cost price) – the
  value figure uses selling price.
