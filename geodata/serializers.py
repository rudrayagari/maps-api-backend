from rest_framework import serializers

from geodata.models import Place, RouteDistance


class AddressSerializer(serializers.Serializer):
    address = serializers.CharField(max_length=255, trim_whitespace=True)


class CoordinateSerializer(serializers.Serializer):
    # Shared validation for any endpoint that accepts raw latitude/longitude.
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()

    def validate_latitude(self, value: float) -> float:
        if value < -90 or value > 90:
            raise serializers.ValidationError("Latitude must be between -90 and 90.")
        return value

    def validate_longitude(self, value: float) -> float:
        if value < -180 or value > 180:
            raise serializers.ValidationError("Longitude must be between -180 and 180.")
        return value


class ReverseGeocodeSerializer(CoordinateSerializer):
    pass


class DistanceSerializer(serializers.Serializer):
    origin = CoordinateSerializer()
    destination = CoordinateSerializer()
    unit = serializers.ChoiceField(
        choices=("meters", "kilometers", "miles"),
        default="kilometers",
    )


class RouteResolveSerializer(serializers.Serializer):
    origin = serializers.CharField(max_length=255, trim_whitespace=True)
    destination = serializers.CharField(max_length=255, trim_whitespace=True)
    unit = serializers.ChoiceField(
        choices=("meters", "kilometers", "miles"),
        default="kilometers",
    )


class PlaceSerializer(serializers.ModelSerializer):
    place_id = serializers.CharField(source="google_place_id")

    class Meta:
        model = Place
        fields = (
            "place_id",
            "formatted_address",
            "latitude",
            "longitude",
            "location_type",
            "partial_match",
            "created_at",
            "updated_at",
        )


class RouteDistanceSerializer(serializers.ModelSerializer):
    origin = PlaceSerializer(source="origin_place")
    destination = PlaceSerializer(source="destination_place")

    class Meta:
        model = RouteDistance
        fields = (
            "id",
            "origin",
            "destination",
            "distance_meters",
            "hit_count",
            "last_requested_at",
            "created_at",
            "updated_at",
        )
