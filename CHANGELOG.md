# Changelog

## v0.1.0 — 2026-07-25

First release.

Reads UK smart meter data from the Hildebrand Glowmarkt platform — the backend
behind the **Bright** app — and feeds it to Home Assistant. No
Glow hardware needed; a SMETS2 meter verified in Bright is enough.

### Highlights

- **History is backfilled, not accumulated.** Long-term statistics are imported
  from the API as external statistics, so the Energy dashboard has your past
  consumption the moment you set it up rather than starting from zero. Depth is
  configurable (default 365 days) and raising it later rebuilds the series rather
  than silently doing nothing.
- **Electricity and gas**, consumption and cost, for every installation on the
  account. Cost is converted from pence to pounds; reactive-power streams are
  ignored.
- **UI configuration** with your Bright email and password, including a reauth
  prompt if the password changes. Tokens last 7 days and renew automatically.

### Entities

One device per installation, with a `<fuel> today` sensor for each stream. These
carry no `state_class` by design — statistics come from the API import path, and
a state_class would make the recorder generate a second, shorter series for the
same data. Point the Energy dashboard at the `glowmarkt:` statistic IDs, not at
the entities.

### Requirements

Home Assistant 2026.4 or newer.

### Known limitations

- DCC data lags roughly 30 minutes; polling is every 30 minutes to match.
- The gas and multi-installation paths are covered by tests but have not yet run
  against a real dual-fuel account. Reports welcome.
- UK only, by nature of the DCC.
