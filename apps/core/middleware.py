class NoStoreMiddleware:
    """Never let browsers or shared-kiosk proxies cache PHI-bearing responses.

    API and media endpoints may return patient data; setting Cache-Control:
    no-store prevents a browser/proxy cache from retaining it (M-05).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith("/api/") or request.path.startswith("/media/"):
            response["Cache-Control"] = "private, no-store, max-age=0"
            response["Pragma"] = "no-cache"
        return response
