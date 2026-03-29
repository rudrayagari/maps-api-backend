from decimal import Decimal
from unittest.mock import patch

from django.db import DatabaseError
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from geodata.models import GeocodeLookup, Place, ReverseGeocodeLookup, RouteDistance
from geodata.services import convert_distance, haversine_distance_meters


class MockGoogleResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("HTTP error")

    def json(self) -> dict:
        return self.payload


def build_geocode_payload(place_id: str, address: str, lat: float, lng: float) -> dict:
    return {
        "status": "OK",
        "results": [
            {
                "place_id": place_id,
                "formatted_address": address,
                "address_components": [],
                "geometry": {
                    "location": {
                        "lat": lat,
                        "lng": lng,
                    },
                    "location_type": "ROOFTOP",
                },
            }
        ],
    }


@override_settings(GOOGLE_MAPS_API_KEY="test-key")
class GeodataApiTests(TestCase):
    def setUp(self) -> None:
        self.client = APIClient()

    @patch("geodata.services.requests.Session.get")
    def test_geocode_endpoint_persists_and_reuses_lookup(self, mock_get) -> None:
        mock_get.return_value = MockGoogleResponse(
            build_geocode_payload(
                "place-1",
                "8500 Beverly Blvd, Los Angeles, CA 90048, USA",
                34.075801,
                -118.376233,
            )
        )

        first = self.client.post("/api/v1/geocode/", {"address": "beverly centre"}, format="json")
        second = self.client.post("/api/v1/geocode/", {"address": "beverly centre"}, format="json")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertFalse(first.json()["cached"])
        self.assertTrue(second.json()["cached"])
        self.assertEqual(mock_get.call_count, 1)
        self.assertEqual(GeocodeLookup.objects.count(), 1)

    @patch("geodata.services.requests.Session.get")
    def test_reverse_geocode_endpoint_returns_formatted_place(self, mock_get) -> None:
        mock_get.return_value = MockGoogleResponse(
            build_geocode_payload(
                "place-2",
                "277 Bedford Ave, Brooklyn, NY 11211, USA",
                40.714224,
                -73.961452,
            )
        )

        response = self.client.post(
            "/api/v1/reverse-geocode/",
            {"latitude": 40.714224, "longitude": -73.961452},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["place"]["formatted_address"],
            "277 Bedford Ave, Brooklyn, NY 11211, USA",
        )
        self.assertEqual(ReverseGeocodeLookup.objects.count(), 1)

    def test_distance_endpoint_returns_expected_units(self) -> None:
        response = self.client.post(
            "/api/v1/distance/",
            {
                "origin": {"latitude": 34.052235, "longitude": -118.243683},
                "destination": {"latitude": 36.169941, "longitude": -115.139832},
                "unit": "miles",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertAlmostEqual(response.json()["distance"]["value"], 228.418, places=3)
        self.assertEqual(response.json()["distance"]["unit"], "miles")

    @patch("geodata.services.requests.Session.get")
    def test_route_resolve_endpoint_geocodes_both_addresses_and_stores_route(self, mock_get) -> None:
        mock_get.side_effect = [
            MockGoogleResponse(
                build_geocode_payload(
                    "origin-place",
                    "1600 Amphitheatre Pkwy, Mountain View, CA 94043, USA",
                    37.4224764,
                    -122.0842499,
                )
            ),
            MockGoogleResponse(
                build_geocode_payload(
                    "destination-place",
                    "1 Apple Park Way, Cupertino, CA 95014, USA",
                    37.3346438,
                    -122.008972,
                )
            ),
        ]

        response = self.client.post(
            "/api/v1/routes/resolve/",
            {
                "origin": "googleplex",
                "destination": "apple park",
                "unit": "kilometers",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["route_cached"])
        self.assertEqual(response.json()["origin"]["place"]["place_id"], "origin-place")
        self.assertEqual(RouteDistance.objects.count(), 1)

    def test_haversine_distance_helper_is_stable(self) -> None:
        distance_meters = haversine_distance_meters(
            40.7128,
            -74.0060,
            34.0522,
            -118.2437,
        )
        distance_miles = convert_distance(distance_meters, "miles")

        self.assertAlmostEqual(float(distance_meters), 3935751.691, places=3)
        self.assertAlmostEqual(float(distance_miles), 2445.563, places=3)

    def test_health_response_includes_request_id_header(self) -> None:
        response = self.client.get("/api/v1/health/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("X-Request-ID", response)

    def test_readiness_response_verifies_database_connectivity(self) -> None:
        response = self.client.get("/api/v1/readiness/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertEqual(response.json()["checks"]["database"], "ok")

    @patch("geodata.views.connection.cursor")
    def test_readiness_returns_503_when_database_check_fails(self, mock_cursor) -> None:
        mock_cursor.side_effect = DatabaseError("db unavailable")

        response = self.client.get("/api/v1/readiness/")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "degraded")
        self.assertEqual(response.json()["checks"]["database"], "error")

    def test_schema_and_docs_endpoints_are_available(self) -> None:
        schema_response = self.client.get("/api/schema/")
        docs_response = self.client.get("/api/docs/")

        self.assertEqual(schema_response.status_code, 200)
        self.assertEqual(docs_response.status_code, 200)

    def test_places_endpoint_supports_search_and_pagination(self) -> None:
        Place.objects.create(
            google_place_id="place-a",
            formatted_address="8500 Beverly Blvd, Los Angeles, CA 90048, USA",
            normalized_formatted_address="8500 beverly blvd, los angeles, ca 90048, usa",
            latitude=Decimal("34.07580100"),
            longitude=Decimal("-118.37623300"),
            location_type="ROOFTOP",
        )
        Place.objects.create(
            google_place_id="place-b",
            formatted_address="1 Apple Park Way, Cupertino, CA 95014, USA",
            normalized_formatted_address="1 apple park way, cupertino, ca 95014, usa",
            latitude=Decimal("37.33464380"),
            longitude=Decimal("-122.00897200"),
            location_type="ROOFTOP",
        )

        response = self.client.get("/api/v1/places/?search=beverly")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["place_id"], "place-a")

    def test_routes_endpoint_supports_search(self) -> None:
        origin = Place.objects.create(
            google_place_id="origin-1",
            formatted_address="8500 Beverly Blvd, Los Angeles, CA 90048, USA",
            normalized_formatted_address="8500 beverly blvd, los angeles, ca 90048, usa",
            latitude=Decimal("34.07580100"),
            longitude=Decimal("-118.37623300"),
            location_type="ROOFTOP",
        )
        destination = Place.objects.create(
            google_place_id="destination-1",
            formatted_address="189 The Grove Dr, Los Angeles, CA 90036, USA",
            normalized_formatted_address="189 the grove dr, los angeles, ca 90036, usa",
            latitude=Decimal("34.07215100"),
            longitude=Decimal("-118.35764000"),
            location_type="ROOFTOP",
        )
        RouteDistance.objects.create(
            origin_place=origin,
            destination_place=destination,
            distance_meters=Decimal("1761.532"),
            hit_count=2,
        )

        response = self.client.get("/api/v1/routes/?origin_search=beverly&destination_search=grove")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["origin"]["place_id"], "origin-1")
