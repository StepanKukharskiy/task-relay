"""Conservative identity for recorded public pages; variants remain distinct."""
from urllib.parse import urlsplit, urlunsplit, unquote_plus

TRACKING = frozenset(('gclid', 'fbclid', 'msclkid', 'tcid', 'afid', 'cpng', 'adgroup'))


def identity(url):
    value = urlsplit(url)
    query = '&'.join(part for part in value.query.split('&') if part and
                    not unquote_plus(part.partition('=')[0]).lower().startswith('utm_') and
                    unquote_plus(part.partition('=')[0]).lower() not in TRACKING)
    return urlunsplit((value.scheme.lower(), value.netloc.lower(), value.path or '/', query, ''))


def association(left, right):
    """Both URLs must be recorded; no arbitrary canonical or redirect inference."""
    if not isinstance(left,str) or not isinstance(right,str) or not left or not right:return None
    if left == right:
        return {'basis': 'exact-recorded-url', 'source_url': left, 'product_url': right}
    if identity(left) == identity(right):
        return {'basis': 'recorded-urls-tracking-only', 'source_url': left, 'product_url': right,
                'identity': identity(left)}
    return None
