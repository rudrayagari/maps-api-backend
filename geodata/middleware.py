import logging
import time
import uuid


request_logger = logging.getLogger("geodata.request")


class RequestCorrelationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started_at = time.monotonic()
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.request_id = request_id

        response = self.get_response(request)

        duration_ms = round((time.monotonic() - started_at) * 1000, 2)
        client_ip = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
        if not client_ip:
            client_ip = request.META.get("REMOTE_ADDR", "")

        response["X-Request-ID"] = request_id
        request_logger.info(
            "request_id=%s method=%s path=%s status=%s duration_ms=%s client_ip=%s",
            request_id,
            request.method,
            request.path,
            response.status_code,
            duration_ms,
            client_ip,
        )

        return response
