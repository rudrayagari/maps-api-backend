# Maps API Backend

Production-oriented Django REST backend for:

- Forward geocoding from free-text addresses.
- Reverse geocoding from latitude/longitude.
- Geometric distance calculation using the haversine formula.
- Route resolution that returns both formatted addresses and the computed distance.

## Features

- Django ORM models compatible with SQLite, PostgreSQL, and MySQL.
- Normalized lookup tables to reduce repeat calls to Google Geocoding.
- Dedicated service layer for Google API access and domain logic.
- JSON-only REST API responses.
- Test coverage for endpoint behavior, caching, and distance math.
- OpenAPI schema and Swagger UI.
- Request correlation IDs and structured request logging.
- Paginated search endpoints for stored places and routes.

## Setup

```bash
cd /Users/sravya/Desktop/maps-api-backend
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Export the environment variables from `.env.example`, then run:

```bash
.venv/bin/python manage.py migrate
.venv/bin/python manage.py runserver
```

Open Swagger UI at `http://127.0.0.1:8000/api/docs/`

Fetch the OpenAPI schema at `http://127.0.0.1:8000/api/schema/`

## API endpoints

`GET /api/v1/health/`

`GET /api/v1/readiness/`

`POST /api/v1/geocode/`

```json
{
  "address": "beverly centre"
}
```

`POST /api/v1/reverse-geocode/`

```json
{
  "latitude": 40.714224,
  "longitude": -73.961452
}
```

`POST /api/v1/distance/`

```json
{
  "origin": {
    "latitude": 34.052235,
    "longitude": -118.243683
  },
  "destination": {
    "latitude": 36.169941,
    "longitude": -115.139832
  },
  "unit": "miles"
}
```

`POST /api/v1/routes/resolve/`

```json
{
  "origin": "beverly centre",
  "destination": "the grove los angeles",
  "unit": "kilometers"
}
```

`GET /api/v1/places/?search=beverly&page=1`

`GET /api/v1/routes/?origin_search=beverly&destination_search=grove&page=1`

## Operational extras

- Responses include `X-Request-ID` for end-to-end request tracing.
- Request logs capture request ID, path, client IP, duration, and response status.
- `readiness` performs a lightweight database connectivity check and returns `503` if the DB is unavailable.

## Database design notes

- `Place` stores normalized canonical locations keyed by Google `place_id`.
- `GeocodeLookup` stores normalized free-text queries and their resolved place.
- `ReverseGeocodeLookup` stores microdegree-rounded coordinates for exact repeat lookup reuse.
- `RouteDistance` stores route distance records keyed by origin and destination place pairs.

This schema keeps the hot path index-friendly and portable across SQLite, PostgreSQL, and MySQL.
