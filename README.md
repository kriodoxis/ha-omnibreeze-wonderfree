# OmniBreeze Wonderfree for Home Assistant

[![GitHub release](https://img.shields.io/github/v/release/miguelcaravantes/ha-omnibreeze-wonderfree)](https://github.com/miguelcaravantes/ha-omnibreeze-wonderfree/releases)
[![HACS validation](https://github.com/miguelcaravantes/ha-omnibreeze-wonderfree/actions/workflows/validate.yml/badge.svg)](https://github.com/miguelcaravantes/ha-omnibreeze-wonderfree/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A local Home Assistant custom integration for the newer OmniBreeze Tower Fan that uses the **Wonderfree** mobile app.

## Supported fan

This integration was developed and tested with:

- Brand: OmniBreeze
- Product: Tower Fan
- Model: **DC2313R**
- Mobile app: **Wonderfree**
- Wonderfree product key: `p11vAZ`

> [!IMPORTANT]
> OmniBreeze also sold an older fan that looks nearly identical but connects through **Tuya / Smart Life**. This integration is only for the newer Wonderfree version. It does not support the Tuya / Smart Life model, and the Tuya integrations will not configure the Wonderfree model.

The DC2313R does not expose Matter through this integration. Instead, the integration communicates directly with the fan over its proprietary local-network protocol.

## Features

- Power control
- Five fan speeds
- Oscillation
- Preset modes: Normal, Natural, Sleep, and Automatic
- Room temperature sensor
- Sound switch
- LED Display switch
- Auto-off timer from 1 to 12 hours
- Automatic local-network discovery
- Automatic recovery when the fan's DHCP address changes
- Configuration and reauthentication through the Home Assistant UI
- Wonderfree account regions:
  - Europe / Latin America
  - North America
  - China

## Local control and cloud use

Normal operation is local. Home Assistant connects directly to the fan on the LAN and does not obtain status from a phone.

Wonderfree cloud access is used only during initial setup or reauthentication to retrieve the fan's local authentication key:

1. Home Assistant sends the email and password directly to the selected Wonderfree regional API over HTTPS.
2. Wonderfree returns a short-lived cloud session token.
3. Home Assistant uses that temporary token to retrieve the fan's local authentication key.
4. The email, password, and cloud session token are discarded and are not stored.
5. Only the local authentication key is saved in Home Assistant's protected config-entry storage.

After setup, the integration makes no Wonderfree cloud requests during normal operation. Power, speed, oscillation, presets, switches, temperature, and timer updates go directly between Home Assistant and the fan over the local network. The Wonderfree cloud is contacted again only if Home Assistant asks you to reauthenticate and retrieve a fresh local key.

The fan may receive a different address from your router after restarting or when its DHCP lease changes. If the saved address stops responding, the integration broadcasts a local discovery request, identifies the fan by its stable device key, updates the saved address, and retries the request. A DHCP reservation is still recommended, but it is no longer required for the integration to recover from an address change.

Because the local key is stored by Home Assistant, Home Assistant backups must be treated as sensitive. The fan and Home Assistant must remain able to reach each other on the local network.

## Requirements

- Home Assistant
- An OmniBreeze DC2313R already added to the Wonderfree app
- Home Assistant and the fan on the same local network/VLAN, with local UDP discovery and TCP traffic allowed
- The Wonderfree account email, password, and account region during setup

## Installation with HACS

This repository can be installed as a HACS custom repository:

1. Open **HACS** in Home Assistant.
2. Select the three-dot menu in the top-right corner and choose **Custom repositories**.
3. Enter:

   ```text
   https://github.com/miguelcaravantes/ha-omnibreeze-wonderfree
   ```

4. Select **Integration** as the category and add the repository.
5. Find **OmniBreeze Wonderfree** in HACS and select **Download**.
6. Restart Home Assistant.
7. Go to **Settings → Devices & services → Add integration** and search for **OmniBreeze Wonderfree**.

## Manual installation

1. Download the latest release from the [Releases page](https://github.com/miguelcaravantes/ha-omnibreeze-wonderfree/releases).
2. Create this directory in your Home Assistant configuration if it does not exist:

   ```text
   /config/custom_components/omnibreeze_wonderfree
   ```

3. Copy the repository's integration files into that directory. `manifest.json` must end up at:

   ```text
   /config/custom_components/omnibreeze_wonderfree/manifest.json
   ```

4. Restart Home Assistant.
5. Go to **Settings → Devices & services → Add integration** and search for **OmniBreeze Wonderfree**.

## Configuration

1. Make sure the fan is powered on and connected to the same network as Home Assistant.
2. Add the **OmniBreeze Wonderfree** integration.
3. Select the discovered fan.
4. Choose the same account region used by the Wonderfree app.
5. Enter the Wonderfree account email and password.

For accounts created in Mexico or elsewhere in Latin America, start with **Europe / Latin America**.

## Troubleshooting

### No supported fans were found

- Confirm this is the Wonderfree version, not the visually identical Tuya / Smart Life version.
- Confirm the fan is online in the Wonderfree app.
- Confirm Home Assistant and the fan are on the same network.
- Check firewall or VLAN rules for UDP discovery and local TCP connections.
- Reload the integration setup while the fan is powered on.

### The email is reported as unregistered

Wonderfree accounts are region-specific. Select the region where the account was created. For Mexico and Latin America, use **Europe / Latin America**.

### Authentication stopped working

Open the integration in **Settings → Devices & services** and complete the reauthentication flow. This retrieves and verifies a fresh local key without storing the Wonderfree password.

## Diagnostics and bug reports

When reporting a problem, include:

- Home Assistant version
- Integration version
- Fan model and Wonderfree region
- Home Assistant diagnostics for the integration
- Relevant logs with personal data removed

Never post a Wonderfree password, local authentication key, Home Assistant token, or unredacted backup.

Please use the [GitHub issue tracker](https://github.com/miguelcaravantes/ha-omnibreeze-wonderfree/issues).

## Disclaimer

This is an independent community project. It is not affiliated with, endorsed by, or supported by OmniBreeze, Costco, Wonderfree, Quectel, or Tuya. Product names are used only to identify compatibility.

## License

[MIT](LICENSE)
