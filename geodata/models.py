from django.db import models
from django.db.models import Q


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Place(TimestampedModel):
    google_place_id = models.CharField(max_length=255, unique=True)
    formatted_address = models.CharField(max_length=512, db_index=True)
    normalized_formatted_address = models.CharField(max_length=512, db_index=True)
    latitude = models.DecimalField(max_digits=11, decimal_places=8)
    longitude = models.DecimalField(max_digits=11, decimal_places=8)
    location_type = models.CharField(max_length=64, blank=True)
    partial_match = models.BooleanField(default=False)
    address_components = models.JSONField(default=list, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["normalized_formatted_address"], name="place_norm_addr_idx"),
            models.Index(fields=["latitude", "longitude"], name="place_lat_lng_idx"),
        ]

    def __str__(self) -> str:
        return self.formatted_address


class GeocodeLookup(TimestampedModel):
    query_text = models.CharField(max_length=255)
    normalized_query = models.CharField(max_length=255)
    query_hash = models.CharField(max_length=64, unique=True)
    place = models.ForeignKey(
        Place,
        on_delete=models.CASCADE,
        related_name="forward_lookups",
    )
    hit_count = models.PositiveBigIntegerField(default=0)
    last_requested_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["normalized_query"], name="geocode_norm_query_idx"),
            models.Index(fields=["place", "last_requested_at"], name="geocode_place_req_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.query_text} -> {self.place_id}"


class ReverseGeocodeLookup(TimestampedModel):
    latitude = models.DecimalField(max_digits=11, decimal_places=8)
    longitude = models.DecimalField(max_digits=11, decimal_places=8)
    latitude_e6 = models.BigIntegerField()
    longitude_e6 = models.BigIntegerField()
    place = models.ForeignKey(
        Place,
        on_delete=models.CASCADE,
        related_name="reverse_lookups",
    )
    hit_count = models.PositiveBigIntegerField(default=0)
    last_requested_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["latitude_e6", "longitude_e6"],
                name="reverse_lookup_latlng_e6_uniq",
            ),
            models.CheckConstraint(
                check=Q(latitude__gte=-90) & Q(latitude__lte=90),
                name="reverse_lookup_lat_valid",
            ),
            models.CheckConstraint(
                check=Q(longitude__gte=-180) & Q(longitude__lte=180),
                name="reverse_lookup_lng_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["place", "last_requested_at"], name="reverse_place_req_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.latitude},{self.longitude} -> {self.place_id}"


class RouteDistance(TimestampedModel):
    origin_place = models.ForeignKey(
        Place,
        on_delete=models.CASCADE,
        related_name="origin_routes",
    )
    destination_place = models.ForeignKey(
        Place,
        on_delete=models.CASCADE,
        related_name="destination_routes",
    )
    distance_meters = models.DecimalField(max_digits=15, decimal_places=3)
    hit_count = models.PositiveBigIntegerField(default=0)
    last_requested_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["origin_place", "destination_place"],
                name="route_origin_destination_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["origin_place", "destination_place", "last_requested_at"],
                name="route_origin_dest_req_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.origin_place_id}->{self.destination_place_id}"
