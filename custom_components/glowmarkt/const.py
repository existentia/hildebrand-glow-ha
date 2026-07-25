"""Constants for the Glowmarkt (Bright) integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Final

DOMAIN: Final = "glowmarkt"

BASE_URL: Final = "https://api.glowmarkt.com/api/v0-1"

# Public application ID for the Bright consumer app, published in the Glowmarkt
# "API Data Retrieval — Individual User for Bright" documentation (v1.8,
# 09 April 2026). It identifies the calling application, not the user.
APPLICATION_ID: Final = "b0f1b774-a586-4f72-9edd-27ead8aa7a8d"

CONF_BACKFILL_DAYS: Final = "backfill_days"
DEFAULT_BACKFILL_DAYS: Final = 365
MAX_BACKFILL_DAYS: Final = 3650

# Consumption data reaches Glowmarkt from the DCC with roughly a 30 minute lag,
# so polling more often than this just burns API calls for no new data.
UPDATE_INTERVAL: Final = timedelta(minutes=30)

# The API caps PT1H reading queries at 31 days. Chunk at 30 to leave headroom so
# an inclusive from/to range can never trip the limit.
HOURLY_CHUNK_DAYS: Final = 30

PERIOD_HOURLY: Final = "PT1H"
PERIOD_DAILY: Final = "P1D"
FUNCTION_SUM: Final = "sum"

# Glowmarkt reports money in pence; Home Assistant wants major units.
PENCE_PER_POUND: Final = 100.0
CURRENCY_GBP: Final = "GBP"


@dataclass(frozen=True, kw_only=True)
class ClassifierInfo:
    """Describes how one Glowmarkt resource classifier maps into HA."""

    label: str
    is_cost: bool
    icon: str


# Only classifiers listed here produce entities and statistics. Reactive-power
# classifiers (electricity.import.reactive / electricity.export.reactive) are
# deliberately omitted: they are only meaningful for large non-domestic sites.
SUPPORTED_CLASSIFIERS: Final[dict[str, ClassifierInfo]] = {
    "electricity.consumption": ClassifierInfo(
        label="Electricity", is_cost=False, icon="mdi:flash"
    ),
    "electricity.consumption.cost": ClassifierInfo(
        label="Electricity cost", is_cost=True, icon="mdi:currency-gbp"
    ),
    "electricity.export": ClassifierInfo(
        label="Electricity export", is_cost=False, icon="mdi:transmission-tower-export"
    ),
    "gas.consumption": ClassifierInfo(label="Gas", is_cost=False, icon="mdi:fire"),
    "gas.consumption.cost": ClassifierInfo(
        label="Gas cost", is_cost=True, icon="mdi:currency-gbp"
    ),
}
