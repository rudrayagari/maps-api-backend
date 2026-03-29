from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

import requests
from django.conf import settings
from django.db import transaction
from django.db.models import F

from geodata.models import GeocodeLookup, Place, ReverseGeocodeLookup, RouteDistance


class GeodataError(Exception):
    pass


class ConfigurationError(GeodataError):
    pass


class UpstreamServiceError(GeodataError):
    pass


class AddressNotFoundError(GeodataError):
    pass


@dataclass(frozen=True)
class GeocodingResult:
    google_place_id: str
    formatted_address: str
    latitude: Decimal
    longitude: Decimal
    location_type: str
    partial_match: bool
    address_components: list
    raw_payload: dict


def normalize_query(value: str) -> str:
    return " ".join(value.strip().split()).casefold()


def hash_query(prefix: str, value: str) -> str:
    return hashlib.sha256(f"{prefix}:{normalize_query(value)}".encode("utf-8")).hexdigest()


def quantize_coordinate(value: float | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)


def coordinate_to_e6(value: float | Decimal) -> int:
    decimal_value = Decimal(str(value)).quantize(
        Decimal("0.000001"),
        rounding=ROUND_HALF_UP,
    )
    return int(decimal_value * 1_000_000)


def haversine_distance_meters(
    origin_lat: float,
    origin_lng: float,
    destination_lat: float,
    destination_lng: float,
) -> Decimal:
    radius_meters = 6_371_008.8
    lat1 = math.radians(origin_lat)
    lat2 = math.radians(destination_lat)
    delta_lat = math.radians(destination_lat - origin_lat)
    delta_lng = math.radians(destination_lng - origin_lng)

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lng / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return Decimal(str(radius_meters * c)).quantize(
        Decimal("0.001"),
        rounding=ROUND_HALF_UP,
    )


def convert_distance(distance_meters: Decimal, unit: str) -> Decimal:
    if unit == "meters":
        divisor = Decimal("1")
    elif unit == "kilometers":
        divisor = Decimal("1000")
    elif unit == "miles":
        divisor = Decimal("1609.344")
    else:
        raise ValueError(f"Unsupported unit: {unit}")

    return (distance_meters / divisor).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def serialize_place(place: Place) -> dict:
    return {
        "place_id": place.google_place_id,
        "formatted_address": place.formatted_address,
        "latitude": float(place.latitude),
        "longitude": float(place.longitude),
        "location_type": place.location_type,
        "partial_match": place.partial_match,
    }


class GoogleGeocodingClient:
    def __init__(self, session: Optional[requests.Session] = None) -> None:
        self.session = session or requests.Session()
        self.base_url = settings.GOOGLE_GEOCODING_BASE_URL
        self.api_key = settings.GOOGLE_MAPS_API_KEY
        self.timeout = settings.GOOGLE_GEOCODING_TIMEOUT_SECONDS

    def geocode(self, address: str) -> GeocodingResult:
        return self._execute({"address": address})

    def reverse_geocode(self, latitude: float, longitude: float) -> GeocodingResult:
        return self._execute({"latlng": f"{latitude},{longitude}"})

    def _execute(self, params: dict) -> GeocodingResult:
        if not self.api_key:
            raise ConfigurationError("GOOGLE_MAPS_API_KEY is not configured.")

        try:
            response = self.session.get(
                self.base_url,
                params={**params, "key": self.api_key},
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise UpstreamServiceError("Google geocoding request failed.") from exc

        payload = response.json()
        status = payload.get("status")

        error_message = payload.get("error_message")

        if status == "ZERO_RESULTS":
            raise AddressNotFoundError("No matching location was found.")
        if status != "OK":
            detail = f"Google geocoding returned an unexpected status: {status or 'UNKNOWN'}."
            if error_message:
                detail = f"{detail} {error_message}"
            raise UpstreamServiceError(
                detail
            )

        results = payload.get("results", [])
        if not results:
            raise AddressNotFoundError("No matching location was found.")

        top_result = results[0]
        geometry = top_result.get("geometry", {})
        location = geometry.get("location", {})

        return GeocodingResult(
            google_place_id=top_result["place_id"],
            formatted_address=top_result["formatted_address"],
            latitude=quantize_coordinate(location["lat"]),
            longitude=quantize_coordinate(location["lng"]),
            location_type=geometry.get("location_type", ""),
            partial_match=bool(top_result.get("partial_match", False)),
            address_components=top_result.get("address_components", []),
            raw_payload=top_result,
        )


def get_or_create_place(result: GeocodingResult) -> Place:
    normalized_formatted_address = normalize_query(result.formatted_address)
    place, _ = Place.objects.update_or_create(
        google_place_id=result.google_place_id,
        defaults={
            "formatted_address": result.formatted_address,
            "normalized_formatted_address": normalized_formatted_address,
            "latitude": result.latitude,
            "longitude": result.longitude,
            "location_type": result.location_type,
            "partial_match": result.partial_match,
            "address_components": result.address_components,
            "raw_payload": result.raw_payload,
        },
    )
    return place


def geocode_address(
    address: str,
    client: Optional[GoogleGeocodingClient] = None,
) -> tuple[Place, bool]:
    query_hash = hash_query("geocode", address)
    lookup = GeocodeLookup.objects.select_related("place").filter(query_hash=query_hash).first()
    if lookup:
        GeocodeLookup.objects.filter(pk=lookup.pk).update(
            hit_count=F("hit_count") + 1,
            query_text=address,
        )
        lookup.refresh_from_db(fields=["hit_count", "query_text", "last_requested_at"])
        return lookup.place, True

    client = client or GoogleGeocodingClient()
    result = client.geocode(address)

    with transaction.atomic():
        place = get_or_create_place(result)
        GeocodeLookup.objects.update_or_create(
            query_hash=query_hash,
            defaults={
                "query_text": address,
                "normalized_query": normalize_query(address),
                "place": place,
                "hit_count": 1,
            },
        )

    return place, False


def reverse_geocode(
    latitude: float,
    longitude: float,
    client: Optional[GoogleGeocodingClient] = None,
) -> tuple[Place, bool]:
    lat_e6 = coordinate_to_e6(latitude)
    lng_e6 = coordinate_to_e6(longitude)
    lookup = (
        ReverseGeocodeLookup.objects.select_related("place")
        .filter(latitude_e6=lat_e6, longitude_e6=lng_e6)
        .first()
    )
    if lookup:
        ReverseGeocodeLookup.objects.filter(pk=lookup.pk).update(hit_count=F("hit_count") + 1)
        lookup.refresh_from_db(fields=["hit_count", "last_requested_at"])
        return lookup.place, True

    client = client or GoogleGeocodingClient()
    result = client.reverse_geocode(latitude, longitude)

    with transaction.atomic():
        place = get_or_create_place(result)
        ReverseGeocodeLookup.objects.update_or_create(
            latitude_e6=lat_e6,
            longitude_e6=lng_e6,
            defaults={
                "latitude": quantize_coordinate(latitude),
                "longitude": quantize_coordinate(longitude),
                "place": place,
                "hit_count": 1,
            },
        )

    return place, False


def resolve_route(
    origin: str,
    destination: str,
    unit: str,
    client: Optional[GoogleGeocodingClient] = None,
) -> dict:
    client = client or GoogleGeocodingClient()
    origin_place, origin_cached = geocode_address(origin, client=client)
    destination_place, destination_cached = geocode_address(destination, client=client)

    computed_distance = haversine_distance_meters(
        float(origin_place.latitude),
        float(origin_place.longitude),
        float(destination_place.latitude),
        float(destination_place.longitude),
    )

    route, created = RouteDistance.objects.get_or_create(
        origin_place=origin_place,
        destination_place=destination_place,
        defaults={
            "distance_meters": computed_distance,
            "hit_count": 1,
        },
    )

    if not created:
        RouteDistance.objects.filter(pk=route.pk).update(
            distance_meters=computed_distance,
            hit_count=F("hit_count") + 1,
        )
        route.refresh_from_db(fields=["distance_meters", "hit_count", "last_requested_at"])

    return {
        "origin": {
            "query": origin,
            "cached": origin_cached,
            "place": serialize_place(origin_place),
        },
        "destination": {
            "query": destination,
            "cached": destination_cached,
            "place": serialize_place(destination_place),
        },
        "distance": {
            "meters": float(route.distance_meters),
            "unit": unit,
            "value": float(convert_distance(route.distance_meters, unit)),
        },
        "route_cached": not created,
    }
