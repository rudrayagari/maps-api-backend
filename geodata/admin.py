from django.contrib import admin

from geodata.models import GeocodeLookup, Place, ReverseGeocodeLookup, RouteDistance


@admin.register(Place)
class PlaceAdmin(admin.ModelAdmin):
    list_display = ("google_place_id", "formatted_address", "latitude", "longitude")
    search_fields = ("google_place_id", "formatted_address")


@admin.register(GeocodeLookup)
class GeocodeLookupAdmin(admin.ModelAdmin):
    list_display = ("query_text", "place", "hit_count", "last_requested_at")
    search_fields = ("query_text", "normalized_query", "query_hash")
    autocomplete_fields = ("place",)


@admin.register(ReverseGeocodeLookup)
class ReverseGeocodeLookupAdmin(admin.ModelAdmin):
    list_display = ("latitude", "longitude", "place", "hit_count", "last_requested_at")
    autocomplete_fields = ("place",)


@admin.register(RouteDistance)
class RouteDistanceAdmin(admin.ModelAdmin):
    list_display = (
        "origin_place",
        "destination_place",
        "distance_meters",
        "hit_count",
        "last_requested_at",
    )
    autocomplete_fields = ("origin_place", "destination_place")
