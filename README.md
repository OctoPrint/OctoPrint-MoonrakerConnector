> [!IMPORTANT]
>
> This plugin requires OctoPrint 2.0.0+ and is still a work in progress.

# Moonraker Connector

Connector plugin to allow connecting to Moonraker enabled Klipper based printers.

Supports connecting, print start & monitoring, file management, macro access, webcam access.

Successfully tested against:

- Qidi Q1 Pro
- Snapmaker U1

This is still a work in progress, please report back any issues or successful tests
at [the plugin's issue tracker](https://github.com/OctoPrint/OctoPrint-MoonrakerConnector/issues).

## Setup

Install via the bundled [Plugin Manager](https://docs.octoprint.org/en/main/bundledplugins/pluginmanager.html)
or manually using this URL:

    https://github.com/OctoPrint/OctoPrint-MoonrakerConnector/archive/main.zip

## Connection

The Moonraker Connector supports entering host, port and API key as connecting parameters. Of these, only the
host to connect to is mandatory. If not provided, port will be set to Moonraker's default port `7125` and
the API key just not used.

### Where to find my host & port?

The correct host to connect to is the IP or host name of your Moonraker instance, usually with port `7125`. If your printer came with
Klipper, Moonraker and a web interface like Fluidd or Mainsail included, go to the included web interface and
use the host name you connect to with port 7125. E.g., if your address bar says `http://10.200.100.101`, use `10.200.100.101`;
if it says `http://q1pro.iot`, use `q1pro.iot`.

### Where to find my API key?

First try connecting without an API key - plenty of vendors seem to ship their printers with Moonraker open to any local client address,
in which case you won't need an API key.

Otherwise, look into the settings of the provided web interface.
