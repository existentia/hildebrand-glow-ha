# Glowmarkt (Bright) — Home Assistant integration

Reads UK smart meter data from the [Hildebrand Glowmarkt](https://glowmarkt.com)
platform — the backend behind the [Bright app](https://glowmarkt.com/bright) — and
makes it available in Home Assistant as sensors and long-term statistics.

No Glow hardware required. If your SMETS2 meter is verified in the Bright app,
Hildebrand can pull delayed half-hourly consumption from the DCC, and this reads
it back out.

## Why this exists

The established community integrations
([HandyHat](https://github.com/HandyHat/ha-hildebrandglow-dcc),
[ColinRobbins](https://github.com/ColinRobbins/ha-hildebrandglow-dcc)) are
abandoned or archived, and the newer ones are thinly maintained. This is a
ground-up implementation with one significant behavioural difference:

**It backfills history.** Glowmarkt serves historical readings, so on first
setup this imports up to a year of hourly consumption as
[external statistics](https://developers.home-assistant.io/docs/core/entity/sensor/#long-term-statistics)
rather than starting from zero and accumulating forward. Your history is there
from the moment you set it up, not a year later.

## What it creates

Two things, which you can use independently.

**Sensor entities** — one device per installation, with a "today so far" sensor
for each stream Glowmarkt exposes:

| Entity | Unit |
| --- | --- |
| `sensor.<installation>_electricity_today` | kWh |
| `sensor.<installation>_electricity_cost_today` | GBP |
| `sensor.<installation>_gas_today` | kWh |
| `sensor.<installation>_gas_cost_today` | GBP |

These are ordinary entities. Put them on any dashboard, use them in automations
and templates, or ignore them entirely.

**Long-term statistics** — hourly history under IDs like
`glowmarkt:electricity_consumption` and `glowmarkt:gas_consumption`. These are
*statistics*, not entities: they hold the backfilled history and are what you
reference anywhere that asks for a statistic rather than an entity.

The entities intentionally carry no `state_class`. Statistics come from the API
import path; adding a state_class would make the recorder generate a second,
shorter series for the same data.

## Setup

You will need a [Bright](https://glowmarkt.com/bright) account with your meter
set up and verified — the same email and password you use in the app.

1. **Install.** In HACS, open the three-dot menu → **Custom repositories**, add
   `https://github.com/existentia/hildebrand-glow-ha` with category
   **Integration**, then find *Glowmarkt (Bright)* and download it.
   Alternatively, copy `custom_components/glowmarkt` into your
   `config/custom_components/` by hand.
2. **Restart Home Assistant.**
3. **Settings → Devices & Services → Add Integration → Glowmarkt**, and sign in.

That is everything the integration needs. The first backfill runs in the
background and can take a minute or two per stream; history depth is
configurable under the integration's options. See
[Using the data](#using-the-data) for what to do with it.

## Using the data

There is no requirement to use Home Assistant's Energy dashboard — it is one
option of several, and it is fine if you have never set it up.

**On any dashboard you already have.** Add the `_today` sensors like any other
entity, with a tile, entities or gauge card.

**To chart the history**, use a **Statistics graph** card and pick a
`glowmarkt:` statistic ID. This is where the backfilled data shows up, and it
works whether or not the Energy dashboard is configured. The **Statistic** card
is the equivalent for a single figure such as this month's total.

**In the Energy dashboard**, if you use it. Go to **Settings → Dashboards →
Energy**. If you have never configured it, this is where you set it up for the
first time; the panel appears in the sidebar once at least one source is
defined. Add `glowmarkt:electricity_consumption` as a grid consumption source,
and `glowmarkt:electricity_consumption_cost` as its cost. Gas is configured the
same way under its own section. Note that these are statistics — pick them from
the statistic picker; the `_today` entities are not what you want here.

**In automations and templates**, use the entities for current values, or the
[statistics websocket API](https://developers.home-assistant.io/docs/api/websocket#fetching-statistics)
for history.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest -q
```

The suite covers the HTTP client (including the 200-with-`valid:false` auth
rejection and the 401 retry), the config and reauth flows, dual-fuel discovery,
statistic-ID disambiguation across multiple installations, and the statistics
backfill — including that raising the history depth rebuilds the series rather
than silently doing nothing.

## Notes and limitations

- DCC data lags roughly 30 minutes. Polling is every 30 minutes; anything faster
  just burns API calls.
- Glowmarkt only collects from the DCC when prompted, so the integration asks
  for a catchup every two hours (the upstream rate limit). Hours it has not
  collected yet are returned as `0` rather than as missing, so a trailing run
  of zeroes is treated as "not in yet" and re-fetched later rather than
  stored.
- Auth tokens last 7 days and are renewed automatically. If your password
  changes, Home Assistant raises a reauth prompt.
- Reactive-power classifiers are ignored — they only matter for large
  non-domestic sites.
- The API caps hourly queries at 31 days, so backfill is chunked at 30.

## Credits

Built against the Glowmarkt *API Data Retrieval — Individual User for Bright*
documentation, v1.8 (9 April 2026).
