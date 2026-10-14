"""Keep OAuth authorization codes and invitation links out of access logs."""
# U is the path without its query string. Never log r (full request), q, or
# Referer: callbacks and invitation redemption URLs contain short-lived secrets.
access_log_format = '%(t)s %(m)s %(U)s %(s)s %(b)s'

