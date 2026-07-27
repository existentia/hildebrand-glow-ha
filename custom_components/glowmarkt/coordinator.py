"""Coordinator and statistics backfill for Glowmarkt."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util, slugify

from .api import GlowmarktAuthError, GlowmarktClient, GlowmarktConnectionError
from .const import (
    BACKFILL_SHUTDOWN_TIMEOUT,
    CATCHUP_INTERVAL,
    CONF_BACKFILL_DAYS,
    CURRENCY_GBP,
    DEFAULT_BACKFILL_DAYS,
    DOMAIN,
    HOURLY_CHUNK_DAYS,
    PENCE_PER_POUND,
    PERIOD_DAILY,
    PERIOD_HOURLY,
    REFRESH_WINDOW_HOURS,
    SUPPORTED_CLASSIFIERS,
    UPDATE_INTERVAL,
    ZERO_TAIL_GRACE_HOURS,
    ClassifierInfo,
)

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1

# Be polite between chunked history requests; a deep backfill is dozens of calls.
CHUNK_DELAY_SECONDS = 0.2


@dataclass(frozen=True, kw_only=True)
class GlowmarktResource:
    """One Glowmarkt data stream, resolved to the things HA needs."""

    resource_id: str
    ve_id: str
    ve_name: str
    classifier: str
    info: ClassifierInfo
    statistic_id: str


class GlowmarktCoordinator(DataUpdateCoordinator[dict[str, float | None]]):
    """Polls today's totals and keeps long-term statistics backfilled."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: GlowmarktClient,
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
            config_entry=entry,
        )
        self.client = client
        self.resources: list[GlowmarktResource] = []
        self._backfill_lock = asyncio.Lock()

        # Remembers how many days of history have actually been imported for
        # each statistic. Without this, raising the backfill option after the
        # first run would do nothing, because the incremental path only ever
        # walks forward from the newest statistic it already holds.
        self._store: Store[dict[str, int]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}.backfill"
        )
        self._depth_applied: dict[str, int] | None = None
        self._last_catchup: datetime | None = None
        self._backfill_task: asyncio.Task[None] | None = None

    @property
    def _backfill_days(self) -> int:
        """How far back to reach on the very first backfill."""
        return int(
            self.config_entry.options.get(CONF_BACKFILL_DAYS, DEFAULT_BACKFILL_DAYS)
        )

    async def _async_setup(self) -> None:
        """Discover meters once, before the first refresh."""
        try:
            virtual_entities = await self.client.async_get_virtual_entities()
        except GlowmarktAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except GlowmarktConnectionError as err:
            raise UpdateFailed(str(err)) from err

        discovered: list[dict[str, Any]] = []
        for entity in virtual_entities:
            ve_id = entity.get("veId")
            if not ve_id:
                continue
            ve_name = entity.get("name") or "Glowmarkt"
            try:
                resources = await self.client.async_get_resources(ve_id)
            except GlowmarktConnectionError as err:
                raise UpdateFailed(str(err)) from err

            for resource in resources:
                classifier = resource.get("classifier")
                info = SUPPORTED_CLASSIFIERS.get(classifier or "")
                resource_id = resource.get("resourceId")
                if info is None or not resource_id:
                    continue
                if resource.get("active") is False:
                    continue
                discovered.append(
                    {
                        "resource_id": resource_id,
                        "ve_id": ve_id,
                        "ve_name": ve_name,
                        "classifier": classifier,
                        "info": info,
                    }
                )

        # Keep statistic IDs short and readable in the single-installation case,
        # which is nearly everyone, but disambiguate by installation name when
        # the same classifier shows up more than once.
        classifier_counts: dict[str, int] = {}
        for item in discovered:
            classifier_counts[item["classifier"]] = (
                classifier_counts.get(item["classifier"], 0) + 1
            )

        self.resources = []
        for item in discovered:
            slug = slugify(item["classifier"])
            if classifier_counts[item["classifier"]] > 1:
                slug = f"{slugify(item['ve_name'])}_{slug}"
            self.resources.append(
                GlowmarktResource(
                    resource_id=item["resource_id"],
                    ve_id=item["ve_id"],
                    ve_name=item["ve_name"],
                    classifier=item["classifier"],
                    info=item["info"],
                    statistic_id=f"{DOMAIN}:{slug}",
                )
            )

        if not self.resources:
            raise UpdateFailed(
                "No supported Glowmarkt resources found on this account"
            )

        _LOGGER.debug(
            "Discovered %d Glowmarkt resources: %s",
            len(self.resources),
            ", ".join(r.statistic_id for r in self.resources),
        )

    async def _async_update_data(self) -> dict[str, float | None]:
        """Fetch today's running total for each resource."""
        now = dt_util.now()
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # The API wants the offset between the requested timezone and UTC,
        # negated: BST (UTC+1) is -60.
        utc_offset = now.utcoffset() or timedelta(0)
        offset_minutes = -int(utc_offset.total_seconds() // 60)

        await self._async_catchup_if_due()

        values: dict[str, float | None] = {}
        try:
            for resource in self.resources:
                readings = await self.client.async_get_readings(
                    resource.resource_id,
                    midnight.replace(tzinfo=None),
                    now.replace(tzinfo=None),
                    PERIOD_DAILY,
                    offset_minutes=offset_minutes,
                )
                value = readings[0][1] if readings else None
                if value is not None and resource.info.is_cost:
                    value = value / PENCE_PER_POUND
                values[resource.resource_id] = value
        except GlowmarktAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except GlowmarktConnectionError as err:
            raise UpdateFailed(str(err)) from err

        # Statistics run separately so a slow first backfill never delays or
        # fails the entity update.
        self._schedule_backfill()

        return values

    def _schedule_backfill(self) -> None:
        """Start a backfill unless one is running or Home Assistant is stopping."""
        if self.hass.is_stopping:
            return
        if self._backfill_task is not None and not self._backfill_task.done():
            return
        self._backfill_task = self.config_entry.async_create_background_task(
            self.hass, self._async_backfill_guarded(), "glowmarkt_backfill"
        )

    async def async_wait_for_backfill(self) -> None:
        """Let an in-flight backfill finish before the entry is torn down.

        Cancelling is not enough. The recorder lookups run in an executor
        thread, and abandoning the awaiting task leaves that thread querying a
        database the recorder may already be disposing of — which segfaults
        rather than raising.
        """
        task = self._backfill_task
        if task is None or task.done():
            return
        with contextlib.suppress(TimeoutError, asyncio.CancelledError):
            async with asyncio.timeout(BACKFILL_SHUTDOWN_TIMEOUT):
                await task

    async def _async_catchup_if_due(self) -> None:
        """Prompt Glowmarkt to pull fresh DCC readings, at most every 2 hours.

        Nothing else triggers this for an API-only consumer. Skip it and the
        platform simply stops collecting, and the readings endpoint answers 0
        for every hour it has no data for — which looks exactly like a house
        that has stopped using electricity.
        """
        now = dt_util.utcnow()
        if (
            self._last_catchup is not None
            and now - self._last_catchup < CATCHUP_INTERVAL
        ):
            return

        self._last_catchup = now
        for resource in self.resources:
            await self.client.async_catchup(resource.resource_id)

    @staticmethod
    def _trim_unreported_tail(
        readings: list[tuple[int, float]], now: datetime
    ) -> list[tuple[int, float]]:
        """Drop a trailing run of zeroes that has not had time to arrive yet.

        A zero at the end of the response nearly always means the reading has
        not been collected, not that nothing was used. Importing it would bake
        the zero into the cumulative sum, and since the incremental pass only
        walks forward, the real figure would never replace it.

        Zeroes older than the grace period are taken at face value, so a
        genuinely idle meter cannot park the cursor indefinitely.
        """
        cutoff = now - timedelta(hours=ZERO_TAIL_GRACE_HOURS)
        end = len(readings)
        while end > 0:
            timestamp, value = readings[end - 1]
            if value != 0:
                break
            if dt_util.utc_from_timestamp(timestamp) < cutoff:
                break
            end -= 1
        return readings[:end]

    async def _async_sum_before(
        self, statistic_id: str, moment: datetime
    ) -> float | None:
        """Return the cumulative sum immediately before `moment`, if known."""
        rows = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period,
            self.hass,
            moment - timedelta(days=7),
            moment,
            {statistic_id},
            "hour",
            None,
            {"sum"},
        )
        series = rows.get(statistic_id) or []
        if not series:
            return None
        return float(series[-1].get("sum") or 0.0)

    async def _async_backfill_guarded(self) -> None:
        """Run the backfill, swallowing errors so the task never explodes."""
        try:
            await self.async_backfill()
        except Exception:  # noqa: BLE001 - background task of last resort
            _LOGGER.exception("Glowmarkt statistics backfill failed")

    async def async_backfill(self) -> None:
        """Bring long-term statistics up to date for every resource."""
        if self._backfill_lock.locked():
            _LOGGER.debug("Backfill already running, skipping this pass")
            return

        async with self._backfill_lock:
            if self._depth_applied is None:
                self._depth_applied = await self._store.async_load() or {}

            for resource in self.resources:
                await self._async_backfill_resource(resource)

            await self._store.async_save(self._depth_applied)

    async def _async_backfill_resource(self, resource: GlowmarktResource) -> None:
        """Import any hourly statistics we do not already hold.

        Rather than importing only strictly-new hours, this re-imports a
        trailing window on every pass, because Glowmarkt readings arrive late
        and get revised. Statistics are keyed by hour, so re-importing replaces
        them in place; the running sum is re-anchored to the last statistic
        before the window so the cumulative series stays consistent.

        If the configured history depth has been increased since the last run,
        the series is instead cleared and rebuilt from the deeper start — rows
        cannot simply be prepended, because `sum` is cumulative and every later
        row would need recomputing.
        """
        assert self._depth_applied is not None
        statistic_id = resource.statistic_id

        now = dt_util.utcnow()
        # Never import the hour in progress: it is still accumulating.
        current_hour = now.replace(minute=0, second=0, microsecond=0)

        requested_days = self._backfill_days
        applied_days = self._depth_applied.get(statistic_id, 0)
        rebuild = requested_days > applied_days

        if rebuild:
            if applied_days:
                _LOGGER.info(
                    "History depth for %s increased from %d to %d days, "
                    "rebuilding the series",
                    statistic_id,
                    applied_days,
                    requested_days,
                )
                # Queued on the recorder's FIFO queue, so it is guaranteed to
                # run before the imports below.
                get_instance(self.hass).async_clear_statistics([statistic_id])
            running_sum = 0.0
            cursor = current_hour - timedelta(days=requested_days)
        else:
            last_stats = await get_instance(self.hass).async_add_executor_job(
                get_last_statistics, self.hass, 1, statistic_id, True, {"sum"}
            )
            if last_stats and last_stats.get(statistic_id):
                row = last_stats[statistic_id][0]
                next_new_hour = dt_util.utc_from_timestamp(row["start"]) + timedelta(
                    hours=1
                )
                # Reach back over the recent window so revised readings — and
                # hours previously stored as 0 because nothing had been
                # collected yet — get replaced with the real figures.
                cursor = min(
                    next_new_hour,
                    current_hour - timedelta(hours=REFRESH_WINDOW_HOURS),
                )
                anchor_sum = await self._async_sum_before(statistic_id, cursor)
                if anchor_sum is None:
                    # Nothing to anchor the running total against, so rewriting
                    # the window would corrupt every later sum. Stay strictly
                    # incremental instead.
                    cursor = next_new_hour
                    running_sum = float(row.get("sum") or 0.0)
                else:
                    running_sum = anchor_sum
            else:
                running_sum = 0.0
                cursor = current_hour - timedelta(days=requested_days)

        if cursor >= current_hour:
            return

        metadata = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=f"{resource.ve_name} {resource.info.label}",
            source=DOMAIN,
            statistic_id=statistic_id,
            unit_class=None,
            unit_of_measurement=(
                CURRENCY_GBP
                if resource.info.is_cost
                else UnitOfEnergy.KILO_WATT_HOUR
            ),
        )

        imported = 0
        while cursor < current_hour:
            if self.hass.is_stopping:
                _LOGGER.debug("Home Assistant is stopping, abandoning backfill")
                return

            chunk_end = min(cursor + timedelta(days=HOURLY_CHUNK_DAYS), current_hour)
            readings = await self.client.async_get_readings(
                resource.resource_id,
                cursor.replace(tzinfo=None),
                (chunk_end - timedelta(seconds=1)).replace(tzinfo=None),
                PERIOD_HOURLY,
                offset_minutes=0,
            )

            # Only the final chunk can have an unreported tail; trimming an
            # intermediate chunk would leave a hole mid-series.
            if chunk_end >= current_hour:
                readings = self._trim_unreported_tail(readings, now)

            batch: list[StatisticData] = []
            for timestamp, value in readings:
                moment = dt_util.utc_from_timestamp(timestamp)
                if moment < cursor or moment >= current_hour:
                    continue
                if resource.info.is_cost:
                    value = value / PENCE_PER_POUND
                running_sum += value
                batch.append(
                    StatisticData(start=moment, state=value, sum=running_sum)
                )

            # Import per chunk rather than accumulating the lot: a deep backfill
            # is tens of thousands of rows, and this way a failure part-way
            # leaves the depth marker unset so the next run simply starts over.
            if batch:
                async_add_external_statistics(self.hass, metadata, batch)
                imported += len(batch)

            cursor = chunk_end
            if cursor < current_hour:
                await asyncio.sleep(CHUNK_DELAY_SECONDS)

        # Recorded even when nothing came back, so a window reaching further
        # back than the meter's own history does not rebuild on every poll.
        self._depth_applied[statistic_id] = max(applied_days, requested_days)

        if imported:
            _LOGGER.debug(
                "Imported %d hourly statistics for %s", imported, statistic_id
            )
