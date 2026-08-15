import time

from django.db import (
    OperationalError,
    ProgrammingError,
    connection,
    transaction,
)
from django.db.models import F

from .models import BusinessSequence


SQLITE_MAX_RETRIES = 10
SQLITE_RETRY_DELAY = 0.05


def next_business_number(key, seed=0):
    """Return a unique monotonically increasing number for a business key."""
    for attempt in range(SQLITE_MAX_RETRIES):
        try:
            with transaction.atomic():
                sequence, created = (
                    BusinessSequence.objects.select_for_update().get_or_create(
                        key=key,
                        defaults={"value": seed},
                    )
                )

                if not created and sequence.value < seed:
                    sequence.value = seed
                    sequence.save(update_fields=["value", "updated_at"])

                BusinessSequence.objects.filter(pk=sequence.pk).update(
                    value=F("value") + 1
                )
                sequence.refresh_from_db(fields=["value"])

                return sequence.value

        except OperationalError:
            if connection.vendor != "sqlite":
                raise

            if attempt == SQLITE_MAX_RETRIES - 1:
                raise

            time.sleep(SQLITE_RETRY_DELAY * (attempt + 1))

        except ProgrammingError:
            # Mantiene operativa una instancia durante una ventana de despliegue
            # previa a la migración. La protección completa se activa al migrar.
            return seed + 1
