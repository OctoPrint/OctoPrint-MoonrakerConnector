import logging

from flask_babel import gettext

import octoprint.plugin
from octoprint.logging.handlers import TriggeredRolloverLogHandler


class MoonrakerJsonRpcLogHandler(TriggeredRolloverLogHandler):
    pass


class MoonrakerConnectorPlugin(
    octoprint.plugin.AssetPlugin,
    octoprint.plugin.TemplatePlugin,
    octoprint.plugin.SettingsPlugin,
    octoprint.plugin.StartupPlugin,
):
    def initialize(self):
        from .connector import ConnectedMoonrakerPrinter  # noqa: F401

        ConnectedMoonrakerPrinter._event_bus = self._event_bus
        ConnectedMoonrakerPrinter._file_manager = self._file_manager
        ConnectedMoonrakerPrinter._plugin_manager = self._plugin_manager
        ConnectedMoonrakerPrinter._plugin_settings = self._settings

        self._jsonrpc_logging_handler = None

    def on_startup(self, host, port):
        self._configure_json_rpc_logging()

    def _configure_json_rpc_logging(self):
        handler = MoonrakerJsonRpcLogHandler(
            self._settings.get_plugin_logfile_path(postfix="jsonrpc"),
            encoding="utf-8",
            backupCount=3,
            delay=True,
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        handler.setLevel(logging.DEBUG)

        logger = logging.getLogger(
            "octoprint.plugins.moonraker_connector.jsonrpc.console"
        )
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

    ##~~ SettingsPlugin mixin

    def get_settings_defaults(self):
        return {
            "emergency_stop_on_cancel": False,
        }

    ##~~ TemplatePlugin mixin

    def get_template_configs(self):
        return [
            {
                "type": "connection_options",
                "name": gettext("Moonraker Connection"),
                "connector": "moonraker",
                "template": "moonraker_connector_connection_option.jinja2",
                "custom_bindings": True,
            }
        ]


__plugin_name__ = "Moonraker Connector"
__plugin_author__ = "Gina Häußge"
__plugin_description__ = "A printer connector plugin to support communication with Klipper-based printers exposing the Moonraker API"
__plugin_license__ = "AGPLv3"
__plugin_pythoncompat__ = ">=3.9,<4"
__plugin_implementation__ = MoonrakerConnectorPlugin()
