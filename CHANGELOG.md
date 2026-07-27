# Changelog

## v0.1.1 — 2026-07-27

Fixes a stall where consumption would stop updating after roughly a day, while
the Bright app carried on showing fresh data.

### Request a DCC catchup

Glowmarkt only pulls new readings from the DCC when something asks it to — the
Bright app does this every time you open it. An API-only consumer that never
asks gets nothing new, and the readings endpoint answers **0** for every hour it
has no data for. That looks exactly like a house that stopped using
electricity.

The integration now calls the catchup endpoint for each resource, at most once
every two hours to stay inside the upstream rate limit.

### Never store an uncollected hour

Those zeroes were previously imported as real readings and baked into the
cumulative sum. Because the incremental pass only walks forward, the true
figures would never have replaced them — the gap would have been permanent.

Two changes prevent that:

- A trailing run of zeroes is now left unimported, on the basis that it means
  "not collected yet" rather than "used nothing". Zeroes older than 48 hours are
  taken at face value, so a genuinely idle meter cannot stall the import.
- A 72-hour trailing window is re-imported on every pass, with the running total
  re-anchored to the statistic before it, so late and revised readings replace
  what was stored. Existing zeroed hours repair themselves on the next pass.

### Do not query the recorder while it is shutting down

The backfill runs as a background task and looks up existing statistics in the
recorder's executor. Nothing stopped it doing so while the recorder was
disposing of its database connections, which segfaults rather than raising.
Unloading now waits for an in-flight backfill to finish rather than cancelling
it — cancelling the awaiting task would not stop the executor thread — and no
backfill is started, or continued between chunks, once Home Assistant is
stopping.

## v0.1.0 — 2026-07-25

First release.

Reads UK smart meter data from the Hildebrand Glowmarkt platform — the backend
behind the **Bright** app — and feeds it to Home Assistant. No
Glow hardware needed; a SMETS2 meter verified in Bright is enough.

### Highlights

- **History is backfilled, not accumulated.** Long-term statistics are imported
  from the API as external statistics, so your past consumption is available the
  moment you set it up rather than starting from zero. Depth is
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
same data. Anywhere that asks for a statistic rather than an entity — a
statistics graph card, or the Energy dashboard if you use one — reference the
`glowmarkt:` statistic IDs, not the entities.

### Requirements

Home Assistant 2026.4 or newer.

### Known limitations

- DCC data lags roughly 30 minutes; polling is every 30 minutes to match.
- The gas and multi-installation paths are covered by tests but have not yet run
  against a real dual-fuel account. Reports welcome.
- UK only, by nature of the DCC.
