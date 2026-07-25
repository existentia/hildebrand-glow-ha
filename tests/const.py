"""Shared fixtures and canned API payloads for the Glowmarkt tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

USERNAME = "meter@example.com"
PASSWORD = "hunter2"

# Well past any test run, so the client never decides the token is stale.
TOKEN_EXP = int(datetime(2099, 1, 1, tzinfo=timezone.utc).timestamp())

AUTH_OK = {
    "valid": True,
    "name": "",
    "accountId": "acc-0001",
    "token": "jwt-token-0001",
    "exp": TOKEN_EXP,
}

# The API answers HTTP 200 with valid=false for a bad password, so this shape
# matters more than the status code.
AUTH_REJECTED = {"valid": False}

VE_ID = "ve-0001"
VE_ID_SECOND = "ve-0002"

RES_ELEC = "res-elec"
RES_ELEC_COST = "res-elec-cost"
RES_GAS = "res-gas"
RES_GAS_COST = "res-gas-cost"
RES_REACTIVE = "res-reactive"

VIRTUAL_ENTITIES = [{"name": "Smart Home", "veId": VE_ID, "resources": []}]

VIRTUAL_ENTITIES_TWO = [
    {"name": "Smart Home", "veId": VE_ID, "resources": []},
    {"name": "Holiday Cottage", "veId": VE_ID_SECOND, "resources": []},
]

# A dual-fuel account. The reactive resource is here on purpose: it must be
# ignored, since it is only meaningful for large non-domestic sites.
RESOURCES_DUAL_FUEL = [
    {
        "resourceId": RES_ELEC,
        "classifier": "electricity.consumption",
        "name": "electricity",
        "baseUnit": "kWh",
        "active": True,
    },
    {
        "resourceId": RES_ELEC_COST,
        "classifier": "electricity.consumption.cost",
        "name": "electricity cost",
        "baseUnit": "pence",
        "active": True,
    },
    {
        "resourceId": RES_GAS,
        "classifier": "gas.consumption",
        "name": "gas",
        "baseUnit": "kWh",
        "active": True,
    },
    {
        "resourceId": RES_GAS_COST,
        "classifier": "gas.consumption.cost",
        "name": "gas cost",
        "baseUnit": "pence",
        "active": True,
    },
    {
        "resourceId": RES_REACTIVE,
        "classifier": "electricity.import.reactive",
        "name": "reactive",
        "baseUnit": "kVARh",
        "active": True,
    },
]

RESOURCES_ELEC_ONLY = [RESOURCES_DUAL_FUEL[0], RESOURCES_DUAL_FUEL[1]]

# Today's totals the fake client hands back: kWh for energy, pence for cost.
DAILY_ENERGY = 12.5
DAILY_COST = 315.0
HOURLY_ENERGY = 0.5
HOURLY_COST = 12.0


class FakeGlowmarktClient:
    """Stands in for GlowmarktClient so tests exercise our logic, not aiohttp.

    Generates one reading per hour across whatever range is asked for, which
    lets the backfill assertions be exact.
    """

    def __init__(
        self,
        virtual_entities: list[dict] | None = None,
        resources: list[dict] | None = None,
    ) -> None:
        """Set up the canned account shape."""
        self.virtual_entities = (
            virtual_entities if virtual_entities is not None else VIRTUAL_ENTITIES
        )
        self.resources = (
            resources if resources is not None else RESOURCES_DUAL_FUEL
        )
        self.readings_calls: list[tuple[str, str]] = []
        self.login_calls = 0

    async def async_login(self) -> None:
        """Pretend to authenticate."""
        self.login_calls += 1

    async def async_get_virtual_entities(self) -> list[dict]:
        """Return the canned virtual entities."""
        return self.virtual_entities

    async def async_get_resources(self, ve_id: str) -> list[dict]:
        """Return the canned resources for any virtual entity."""
        return self.resources

    async def async_get_readings(
        self,
        resource_id: str,
        start: datetime,
        end: datetime,
        period: str,
        *,
        offset_minutes: int = 0,
        function: str = "sum",
    ) -> list[tuple[int, float]]:
        """Return canned readings for the requested window."""
        self.readings_calls.append((resource_id, period))
        is_cost = resource_id.endswith("cost")

        if period == "P1D":
            value = DAILY_COST if is_cost else DAILY_ENERGY
            return [(int(start.replace(tzinfo=timezone.utc).timestamp()), value)]

        value = HOURLY_COST if is_cost else HOURLY_ENERGY
        readings: list[tuple[int, float]] = []
        cursor = start.replace(tzinfo=timezone.utc, minute=0, second=0, microsecond=0)
        limit = end.replace(tzinfo=timezone.utc)
        while cursor <= limit:
            readings.append((int(cursor.timestamp()), value))
            cursor += timedelta(hours=1)
        return readings
