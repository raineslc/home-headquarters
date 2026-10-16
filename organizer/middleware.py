class PrivateResponses:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response['Cache-Control'] = 'private, no-store'
        response['Content-Security-Policy'] = "default-src 'self'; base-uri 'self'; frame-ancestors 'none'; form-action 'self' https://accounts.google.com https://www.google.com; object-src 'none'"
        if request.path.startswith('/connections/google/callback') or request.path.startswith('/join/'):
            response['Referrer-Policy'] = 'no-referrer'
        # Voice input (AI-09) needs the microphone on this site's own pages only.
        response['Permissions-Policy'] = 'camera=(), microphone=(self), geolocation=()'
        return response
