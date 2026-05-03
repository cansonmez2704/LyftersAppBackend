"""
WSGI config for core project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os

# When running under gevent workers, psycopg2's C-level blocking I/O would
# stall each worker on every DB call. psycogreen wraps psycopg2's wait
# callback so it yields to the gevent loop. Only patch when gevent has
# actually monkey-patched socket — under sync workers gevent may still be
# importable (because locust pulled it in), but is_module_patched is False.
try:
    from gevent.monkey import is_module_patched
    if is_module_patched("socket"):
        from psycogreen.gevent import patch_psycopg
        patch_psycopg()
except ImportError:
    pass

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

application = get_wsgi_application()
