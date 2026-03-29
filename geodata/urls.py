from django.urls import path

from geodata.views import (
    DistanceView,
    GeocodeView,
    HealthView,
    PlaceListView,
    ReadinessView,
    ReverseGeocodeView,
    RouteDistanceListView,
    RouteResolveView,
)

urlpatterns = [
    # Operational endpoints.
    path("health/", HealthView.as_view(), name="health"),
    path("readiness/", ReadinessView.as_view(), name="readiness"),
    # Core assignment endpoints.
    path("geocode/", GeocodeView.as_view(), name="geocode"),
    path("reverse-geocode/", ReverseGeocodeView.as_view(), name="reverse-geocode"),
    path("distance/", DistanceView.as_view(), name="distance"),
    path("routes/resolve/", RouteResolveView.as_view(), name="route-resolve"),
    # Supporting endpoints for inspecting stored results.
    path("places/", PlaceListView.as_view(), name="place-list"),
    path("routes/", RouteDistanceListView.as_view(), name="route-list"),
]
