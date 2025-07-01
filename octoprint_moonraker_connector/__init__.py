import logging

from flask_babel import gettext

import octoprint.plugin


class MoonrakerConnectorPlugin(
    octoprint.plugin.AssetPlugin,
    octoprint.plugin.TemplatePlugin,
    octoprint.plugin.SettingsPlugin,
    octoprint.plugin.StartupPlugin,
):
    def initialize(self):
        self._jsonrpc_logger = logging.getLogger(
            "octoprint.plugins.moonraker_connector.jsonrpc.console"
        )

    def on_startup(self, host, port):
        jsonrpc_logging_handler = logging.handlers.RotatingFileHandler(
            self._settings.get_plugin_logfile_path(postfix="jsonrpc"),
            maxBytes=2 * 1024 * 1024,
            encoding="utf-8",
        )
        jsonrpc_logging_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        jsonrpc_logging_handler.setLevel(logging.DEBUG)

        self._jsonrpc_logger.addHandler(jsonrpc_logging_handler)
        self._jsonrpc_logger.setLevel(logging.DEBUG)
        self._jsonrpc_logger.propagate = False

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


def __plugin_load__():
    from .connector import ConnectedMoonrakerPrinter  # noqa: F401
