from django.db import DatabaseError, connection
from django.db.models import Q
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from geodata.models import Place, RouteDistance
from geodata.serializers import (
    AddressSerializer,
    DistanceSerializer,
    PlaceSerializer,
    ReverseGeocodeSerializer,
    RouteDistanceSerializer,
    RouteResolveSerializer,
)
from geodata.services import (
    AddressNotFoundError,
    ConfigurationError,
    UpstreamServiceError,
    convert_distance,
    geocode_address,
    haversine_distance_meters,
    reverse_geocode,
    resolve_route,
    serialize_place,
)


class HealthView(APIView):
    authentication_classes = []
    permission_classes = []

    @extend_schema(
        responses={200: {"type": "object", "properties": {"status": {"type": "string"}}}},
    )
    def get(self, request):
        # Liveness probe: if Django can answer, the process is up.
        return Response({"status": "ok"})


class ReadinessView(APIView):
    authentication_classes = []
    permission_classes = []

    @extend_schema(
        responses={200: {"type": "object"}, 503: {"type": "object"}},
    )
    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except DatabaseError as exc:
            return Response(
                {
                    "status": "degraded",
                    "checks": {
                        "database": "error",
                    },
                    "detail": str(exc),
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(
            {
                "status": "ok",
                "checks": {
                    "database": "ok",
                },
            }
        )


class GeocodeView(APIView):
    authentication_classes = []
    permission_classes = []

    @extend_schema(
        request=AddressSerializer,
        responses={200: {"type": "object"}},
        examples=[
            OpenApiExample(
                "Forward geocode",
                value={"address": "beverly centre"},
                request_only=True,
            )
        ],
    )
    def post(self, request):
        # Forward geocode free-text input into a canonical place record.
        serializer = AddressSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            place, cached = geocode_address(serializer.validated_data["address"])
        except AddressNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except ConfigurationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except UpstreamServiceError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(
            {
                "query": serializer.validated_data["address"],
                "cached": cached,
                "place": serialize_place(place),
            }
        )


class ReverseGeocodeView(APIView):
    authentication_classes = []
    permission_classes = []

    @extend_schema(
        request=ReverseGeocodeSerializer,
        responses={200: {"type": "object"}},
    )
    def post(self, request):
        # Reverse geocode raw coordinates into a canonical place record.
        serializer = ReverseGeocodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            place, cached = reverse_geocode(data["latitude"], data["longitude"])
        except AddressNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except ConfigurationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except UpstreamServiceError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(
            {
                "query": {
                    "latitude": data["latitude"],
                    "longitude": data["longitude"],
                },
                "cached": cached,
                "place": serialize_place(place),
            }
        )


class DistanceView(APIView):
    authentication_classes = []
    permission_classes = []

    @extend_schema(
        request=DistanceSerializer,
        responses={200: {"type": "object"}},
    )
    def post(self, request):
        # Pure geometric distance endpoint; this path never depends on Google.
        serializer = DistanceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        origin = data["origin"]
        destination = data["destination"]
        distance_meters = haversine_distance_meters(
            origin["latitude"],
            origin["longitude"],
            destination["latitude"],
            destination["longitude"],
        )

        return Response(
            {
                "origin": origin,
                "destination": destination,
                "distance": {
                    "meters": float(distance_meters),
                    "unit": data["unit"],
                    "value": float(convert_distance(distance_meters, data["unit"])),
                },
            }
        )


class RouteResolveView(APIView):
    authentication_classes = []
    permission_classes = []

    @extend_schema(
        request=RouteResolveSerializer,
        responses={200: {"type": "object"}},
    )
    def post(self, request):
        # Resolves both addresses and returns the formatted places plus distance.
        serializer = RouteResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            payload = resolve_route(
                origin=serializer.validated_data["origin"],
                destination=serializer.validated_data["destination"],
                unit=serializer.validated_data["unit"],
            )
        except AddressNotFoundError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_404_NOT_FOUND)
        except ConfigurationError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except UpstreamServiceError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(payload)


class PlaceListView(generics.ListAPIView):
    authentication_classes = []
    permission_classes = []
    serializer_class = PlaceSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="search",
                description="Case-insensitive substring match against formatted addresses.",
                required=False,
                type=str,
            ),
            OpenApiParameter(name="page", required=False, type=int),
        ],
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        queryset = Place.objects.all().order_by("id")
        search = self.request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(formatted_address__icontains=search)
                | Q(normalized_formatted_address__icontains=search.casefold())
                | Q(google_place_id__iexact=search)
            )
        return queryset


class RouteDistanceListView(generics.ListAPIView):
    authentication_classes = []
    permission_classes = []
    serializer_class = RouteDistanceSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="origin_search",
                description="Search origin formatted address.",
                required=False,
                type=str,
            ),
            OpenApiParameter(
                name="destination_search",
                description="Search destination formatted address.",
                required=False,
                type=str,
            ),
            OpenApiParameter(name="page", required=False, type=int),
        ],
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        queryset = RouteDistance.objects.select_related(
            "origin_place",
            "destination_place",
        ).order_by("-last_requested_at", "-id")

        origin_search = self.request.query_params.get("origin_search", "").strip()
        destination_search = self.request.query_params.get("destination_search", "").strip()

        if origin_search:
            queryset = queryset.filter(
                origin_place__formatted_address__icontains=origin_search
            )
        if destination_search:
            queryset = queryset.filter(
                destination_place__formatted_address__icontains=destination_search
            )
        return queryset
