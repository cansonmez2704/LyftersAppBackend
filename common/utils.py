import logging
from django.db.models import Model
from django.db import OperationalError

logger = logging.getLogger(__name__)

def lock_profiles_for_update(pk1: int, pk2: int, profile_model: type[Model]) -> dict[int, Model]:
    """
    Safely acquires row-level locks for two profiles, preventing circular deadlocks
    by sorting the primary keys before locking.
    """
    ordered_pks = sorted([pk1, pk2])
    try:
        # Returns a dictionary mapping PK to the locked profile instance
        return {
            p.pk: p
            for p in profile_model.objects.select_for_update().filter(pk__in=ordered_pks)
        }
    except OperationalError as e:
        logger.error("Lock timeout while acquiring profiles %s and %s: %s", pk1, pk2, e)
        raise  # Re-raise to trigger an HTTP 503/500 depending on middleware