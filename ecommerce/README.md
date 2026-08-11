# eCommerce Catalog API

Production-ready Django 5 + DRF backend for a beauty/kitchen eCommerce store.

---

## Tech stack

| Layer | Library |
|-------|---------|
| Framework | Django 5.x |
| API | Django REST Framework |
| Database | PostgreSQL |
| Filtering | django-filter |
| CORS | django-cors-headers |
| Images | Pillow |

---

## Quick start

```bash
# 1. Clone / extract this folder
cd catalog_app

# 2. Create & activate a virtual environment
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with your PostgreSQL credentials

# 5. Create the database (PostgreSQL)
createdb ecommerce_db

# 6. Run migrations
python manage.py migrate

# 7. Create a superuser (optional)
python manage.py createsuperuser

# 8. Start the development server
python manage.py runserver
```

The API will be available at `http://127.0.0.1:8000/api/`.

---

## Project structure

```
catalog_app/
├── catalog/               ← Django app (models, views, serializers)
│   ├── models.py
│   ├── serializers.py
│   ├── views.py
│   ├── urls.py
│   ├── filters.py
│   ├── exceptions.py
│   ├── admin.py
│   └── apps.py
├── ecommerce/             ← Django project (settings, root urls)
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── manage.py
├── requirements.txt
└── .env.example
```

---

## API endpoints

### Categories

| Method | URL | Description |
|--------|-----|-------------|
| GET | `/api/categories/` | List active categories |
| POST | `/api/categories/` | Create category |
| GET | `/api/categories/{id}/` | Retrieve category |
| PUT | `/api/categories/{id}/` | Update category |
| DELETE | `/api/categories/{id}/` | Soft-delete category |
| GET | `/api/categories/tree/` | Hierarchical tree |

### Products

| Method | URL | Description |
|--------|-----|-------------|
| GET | `/api/products/` | Paginated list (filter + search) |
| POST | `/api/products/` | Create product |
| GET | `/api/products/{id}/` | Product detail |
| PUT | `/api/products/{id}/` | Full update |
| PATCH | `/api/products/{id}/` | Partial update |
| DELETE | `/api/products/{id}/` | Soft-delete |
| GET | `/api/products/featured/` | Featured products |
| GET | `/api/products/search/?search=term` | Search |
| GET | `/api/products/by-category/{slug}/` | By category |

### Variants

| Method | URL | Description |
|--------|-----|-------------|
| GET | `/api/products/{product_id}/variants/` | List variants |
| POST | `/api/products/{product_id}/variants/` | Add variant |
| GET | `/api/variants/{id}/` | Variant detail |
| PUT | `/api/variants/{id}/` | Update variant |
| DELETE | `/api/variants/{id}/` | Soft-delete variant |

### Images

| Method | URL | Description |
|--------|-----|-------------|
| POST | `/api/products/{product_id}/images/` | Upload image |
| DELETE | `/api/images/{id}/` | Delete image |

---

## Filtering & search

```
GET /api/products/?category=skin-care
GET /api/products/?brand=Botanica
GET /api/products/?min_price=5&max_price=50
GET /api/products/?featured=true
GET /api/products/?search=rose+cream
GET /api/products/?ordering=-price
GET /api/products/?page=2&page_size=10
```

---

## Response envelope

**Success:**
```json
{
    "status": "success",
    "data": { ... }
}
```

**Paginated list:**
```json
{
    "status": "success",
    "count": 100,
    "next": "http://...?page=3",
    "previous": "http://...?page=1",
    "data": [ ... ]
}
```

**Validation error (400):**
```json
{
    "status": "error",
    "message": "Validation failed.",
    "errors": {
        "sale_price": ["sale_price must be less than or equal to base_price."]
    }
}
```

**Not found (404):**
```json
{
    "status": "error",
    "message": "Resource not found."
}
```

---

## Permissions

- **Anonymous users** – read-only (GET)
- **Authenticated users** – full CRUD

Authentication uses Django session auth by default.  
To enable JWT, uncomment `djangorestframework-simplejwt` in `requirements.txt` and update `REST_FRAMEWORK` in `settings.py`.

---

## Key model behaviours

- **UUID primary keys** on all main entities
- **Slug auto-generation** with uniqueness protection
- **Soft deletion** via `is_active` flag (no DB rows deleted)
- **sale_price ≤ base_price** enforced at model + serializer level
- **Duplicate variant attributes** rejected per product
- **Only one default variant** per product enforced automatically
- **Timezone-aware timestamps** (`USE_TZ = True`)
