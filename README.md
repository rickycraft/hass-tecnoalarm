# Tecnoalarm for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/rickycraft/hass-tecnoalarm)

A custom Home Assistant integration for monitoring Tecnoalarm alarm panels over a direct local TCP connection.

**Unofficial community integration.** This project is not developed, endorsed, or supported by Tecnoalarm and is not affiliated with Tecnoalarm.

**The integration is currently read-only.** It reports panel and program status. Arming, disarming, triggering the alarm, and changing panel settings are not supported.

## Features

- One alarm control panel entity per program accessible to your user code, showing its name and arming state.
- Separate binary sensors for panel-wide alarm and fault indicators.
- Configurable local polling from 1 to 600 seconds (default: 30).
- Configuration through the Home Assistant UI.
- Optional persistent connection with automatic reconnection.

## Installation

### HACS

1. Open **HACS**, then the menu → **Custom repositories**.
2. Add `https://github.com/rickycraft/hass-tecnoalarm` with type **Integration**.
3. Find **Tecnoalarm** in HACS and download it.
4. Restart Home Assistant.
5. Go to **Settings → Devices & services → Add integration** and search for **Tecnoalarm**.

This repository is installed as a HACS custom repository; it is not currently listed in the default HACS catalog.

### Manual installation

1. Download the project from [GitHub](https://github.com/rickycraft/hass-tecnoalarm).
2. Copy `custom_components/tecnoalarm` into your Home Assistant configuration directory, preserving the full directory contents:

   ```text
   config/
     custom_components/
       tecnoalarm/
         manifest.json
         ...
   ```

3. Restart Home Assistant, then add **Tecnoalarm** under **Settings → Devices & services**.

## Configuration

You need a panel with direct TCP access enabled, reachable from Home Assistant, and valid connection credentials.

| Field | Description |
| --- | --- |
| Host | Panel IP address or hostname. |
| Port | Direct TCP port; defaults to `10001`. |
| APPID | Your app's hexadecimal APPID, 1–4 digits, for example `0462`. Use your actual value. |
| Passphrase | Panel's direct-access passphrase; this can differ from a cloud registration passphrase. |
| User code | Numeric panel user code, 4–6 digits. Preserve leading zeros. |
| Polling interval | Seconds between polls, from `1` to `600`; defaults to `30`. Set to `0` to keep authentication open. |

Setup validates authentication before saving. The integration connects directly to the panel; cloud registration and cloud connections are not part of the Home Assistant setup.

You can change **Polling interval** later under **Reconfigure** or **Configure**. Saving changes reloads the integration.

To update credentials or connection details, open the integration entry and select **Reconfigure** or **Configure**.

With a positive polling interval, each poll connects, authenticates, reads status, and disconnects. Set the interval to `0` to reuse the authenticated connection, send a read-only keepalive every 5 seconds, and read status every 30 seconds. Zero selects the persistent connection mode; it does not disable status updates. An explicitly enabled legacy persistent connection setting is treated as `0` until the interval is saved.

When saving either form, the integration waits for any active status read or keepalive to finish, pauses background panel traffic, and disconnects the current session before validating the credentials. On success it stays paused until the integration reloads. On failure it resumes using the previous settings. Opening or cancelling the form without saving does not interrupt monitoring.

## Reported states

| Program status | Home Assistant state |
| --- | --- |
| Idle | Disarmed |
| Pre-exit, exit, or partial exit | Arming |
| Fully armed | Armed away |
| Partially armed | Armed custom bypass |
| Partial end or unrecognized status | Unknown |

Program entities expose `protocol_state`, `raw_status`, and `program_number` attributes. They advertise no control features and reject control actions locally.

The panel alarm indicator is panel-wide; it does not set individual program entities to **Triggered**. Entities become unavailable when status reads fail. Programs that become accessible are added automatically, and programs that lose permission become unavailable.

## Compatibility and limitations

This is an early integration. Authentication, status polling, and connection reuse have been checked against one locally configured panel. Status interpretation and program names remain provisional, and the integration still needs validation in a real Home Assistant instance.

The decoder recognizes models in the TP256, TP512C, TP96V, TP828, TP888, TP440, TP42, TP312, EV424, EV50, and EV150 families, including selected variants listed in [the decoder](custom_components/tecnoalarm/client/status.py). Decoder coverage does not establish hardware compatibility; other models and firmware versions need testing. Unknown model identifiers are rejected.

For now, only program arming states and panel-wide alarm/fault indicators are exposed. Zone monitoring and alarm control are not implemented.

## Development

Install Python 3 and the dependencies used by the client and local tests:

```bash
python3 -m pip install -r requirements-dev.txt
make test
```

The tests use mocked connections and small Home Assistant API doubles. They do not contact a real panel and do not replace testing inside Home Assistant. Home Assistant installs the integration's runtime dependency automatically.

## Support

Report problems or compatibility results in [GitHub Issues](https://github.com/rickycraft/hass-tecnoalarm/issues). Include the panel model, firmware version, Home Assistant version, and relevant errors. Remove credentials and identifying panel details from logs before sharing them.

This is an unofficial community project and is not affiliated with Tecnoalarm.

## License

Licensed under the [MIT License](LICENSE). Commercial and noncommercial use are permitted under its terms.
