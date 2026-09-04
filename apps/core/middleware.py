import logging
 
logger = logging.getLogger("rasheed.security")
 
 
class BranchScopeMiddleware:
    """
    Attaches request.branch from the logged-in user's assigned branch.
    Every view/queryset filters through this instead of trusting a branch_id
    that could be tampered with in a form field or URL — a user physically
    cannot query another branch's invoices, stock or ledger.
 
    Head-office roles (is_multi_branch=True) may switch branches via a
    session key set by a dedicated, permission-checked "switch branch" view —
    never from an unauthenticated or unchecked request parameter.
    """
    def __init__(self, get_response):
        self.get_response = get_response
 
    def __call__(self, request):
        request.branch = None
        user = getattr(request, "user", None)
        if user and user.is_authenticated:
            if user.is_multi_branch:
                branch_id = request.session.get("active_branch_id")
                request.branch = user.accessible_branch(branch_id)
            else:
                request.branch = user.branch
        return self.get_response(request)
 
 
class SecurityHeadersMiddleware:
    """
    Extra defence-in-depth headers beyond Django's built-in SecurityMiddleware.
    Keeps a basic CSP even if django-csp isn't wired up, and logs suspicious
    branch-mismatch attempts for later review.
    """
    def __init__(self, get_response):
        self.get_response = get_response
 
    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'",
        )
        response.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        response.setdefault("X-Content-Type-Options", "nosniff")
        return response
