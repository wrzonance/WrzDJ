"""Shared pagination bounds for public guest-facing list endpoints.

These bound the *payload size of a single request* — a denial-of-service /
response-size guard, not a product-level ceiling. Clients page through larger
result sets with ``offset``; the endpoints always report the true ``total`` so
callers know how many rows exist beyond the current page.

History: the collect leaderboard and join request list previously hard-capped
at ``.limit(200)`` / ``.limit(50)`` with ``total=len(rows)``. That silently hid
every row past the cap and reported a frozen, wrong count. The cap below is a
real upper bound a client cannot exceed in one call, but it no longer doubles
as a hidden display ceiling.
"""

# Default page size when a client omits ``limit``.
DEFAULT_PAGE_SIZE = 100

# Hard upper bound on a single page. ~500 rows keeps JSON payloads small enough
# for mobile guests on /join and /collect while sitting far above any realistic
# single-event request count. Raise only alongside multi-page client fetching.
MAX_PAGE_SIZE = 500
