# Glowmarkt (Bright) — Home Assistant integration

Reads UK smart meter data from the [Hildebrand Glowmarkt](https://glowmarkt.com)
platform — the backend behind the [Bright app](https://glowmarkt.com/bright) — and feeds it to Home
Assistant's Energy dashboard.

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
rather than starting from zero and accumulating forward. The Energy dashboard
has your history immediately.

## What it creates

One device per installation, and for each data stream Glowmarkt exposes:

| Entity | Unit |
| --- | --- |
| `sensor.<installation>_electricity_today` | kWh |
| `sensor.<installation>_electricity_cost_today` | GBP |
| `sensor.<installation>_gas_today` | kWh |
| `sensor.<installation>_gas_cost_today` | GBP |

Plus long-term statistics under `glowmarkt:electricity_consumption`,
`glowmarkt:gas_consumption`, and so on. **Those statistic IDs are what you point
the Energy dashboard at**, not the entities.

The entities intentionally carry no `state_class`. Statistics come from the API
import path; adding a state_class would make the recorder generate a second,
shorter series for the same data.

## Setup

1. Install via HACS as a custom repository, or copy `custom_components/glowmarkt`
   into your `config/custom_components/`.
2. Restart Home Assistant.
3. **Settings → Devices & Services → Add Integration → Glowmarkt**, and sign in
   with your Bright email and password.
4. **Settings → Dashboards → Energy**, and add `glowmarkt:electricity_consumption`
   as the grid consumption source (and the cost statistic alongside it).

The first backfill runs in the background and can take a minute or two per
stream. History depth is configurable under the integration's options.

## Notes and limitations

- DCC data lags roughly 30 minutes. Polling is every 30 minutes; anything faster
  just burns API calls.
- Auth tokens last 7 days and are renewed automatically. If your password
  changes, Home Assistant raises a reauth prompt.
- Reactive-power classifiers are ignored — they only matter for large
  non-domestic sites.
- The API caps hourly queries at 31 days, so backfill is chunked at 30.

## Credits

Built against the Glowmarkt *API Data Retrieval — Individual User for Bright*
documentation, v1.8 (9 April 2026).
