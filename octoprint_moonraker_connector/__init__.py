import logging
from typing import Optional
from urllib.parse import urljoin

import requests
import subprocess
from flask import jsonify
from flask_babel import gettext

import octoprint.plugin
from octoprint.logging.handlers import TriggeredRolloverLogHandler
from octoprint.util.url import set_url_query_param

from . import schema

URL_KLIPPER_RESTART_MOONRAKER = "http://{host}:{port}/machine/services/restart"
URL_FIRMWARE_RESTART_MOONRAKER = "http://{host}:{port}/printer/firmware_restart"
URL_HOST_RESTART_MOONRAKER = "http://{host}:{port}/printer/restart"
URL_WEBCAM_INFO_MOONRAKER = "http://{host}:{port}/server/webcams/list"
URL_WEBCAM_INFO_FLUIDD_LEGACY = (
    "http://{host}:{port}/server/database/item?namespace=fluidd&key=cameras"
)

FLUIDD_LEGACY_CAMERA_TYPES = {
    "mjpgstream": "mjpegstreamer",
    "mjpgadaptive": "mjpegstreamer-adaptive",
}
MJPEG_STREAMER_WEBCAM_SERVICES = ("mjpegstreamer", "mjpegstreamer-adaptive")


class MoonrakerJsonRpcLogHandler(TriggeredRolloverLogHandler):
    pass


class MoonrakerConnectorPlugin(
    octoprint.plugin.AssetPlugin,
    octoprint.plugin.TemplatePlugin,
    octoprint.plugin.SettingsPlugin,
    octoprint.plugin.SimpleApiPlugin,
    octoprint.plugin.StartupPlugin,
):
    def initialize(self):
        # this not only imports but also registers the connector with the system!
        from .connector import ConnectedMoonrakerPrinter

        # inject properties into connector class
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

    ##~~ SimpleApiPlugin

    def on_api_get(self, request):
        webcams = []

        params = self._get_connector_params()
        if params is not None:
            host = params["host"]
            port = params["port"]
            apikey = params["apikey"]

            if host is not None and port is not None:
                webcams = self._get_all_webcams(host, port, apikey=apikey)

        response = schema.ApiResponse(
            webcams=[self._to_api_webcam(webcam) for webcam in webcams]
        )
        return jsonify(response.model_dump(by_alias=True))

    def get_api_commands(self):
        return dict(
            restart_host=[],
            restart_firmware=[],
            restart_klipper_service=[]
        )

    def on_api_command(self, command, data):
        if command == "restart_host":
            params = self._get_connector_params()
            if params is not None:
                host = params["host"]
                port = params["port"]
                apikey = params["apikey"]

                if host is not None and port is not None:
                    headers = {}
                    if apikey:
                        headers["X-Api-Key"] = apikey

                    r = requests.post(
                        URL_HOST_RESTART_MOONRAKER.format(host=host, port=port), headers=headers
                    )
                    ret = r.json()

            if ret['result'] == "ok":
                return jsonify(success=True, message="Host Restart sent")
            else:
                return jsonify(success=False, message="Host Restart failed")
        elif command == "restart_firmware":
            params = self._get_connector_params()
            if params is not None:
                host = params["host"]
                port = params["port"]
                apikey = params["apikey"]

                if host is not None and port is not None:
                    headers = {}
                    if apikey:
                        headers["X-Api-Key"] = apikey

                    r = requests.post(
                        URL_FIRMWARE_RESTART_MOONRAKER.format(host=host, port=port), headers=headers
                    )
                    ret = r.json()

            if ret['result'] == "ok":
                return jsonify(success=True, message="Firmware Restart sent")
            else:
                return jsonify(success=False, message="Firmware Restart failed")
        if command == "restart_klipper_service":
            params = self._get_connector_params()
            if params is not None:
                host = params["host"]
                port = params["port"]
                apikey = params["apikey"]

                if host is not None and port is not None:
                    headers = {}
                    if apikey:
                        headers["X-Api-Key"] = apikey

                    payload = {
                        "service": "klipper"
                    }

                    r = requests.post(
                        URL_KLIPPER_RESTART_MOONRAKER.format(host=host, port=port), headers=headers, json=payload
                    )
                    ret = r.json()

            if ret['result'] == "ok":
                return jsonify(success=True, message="Klipper Restart sent")
            else:
                return jsonify(success=False, message="Klipper Restart failed")

    def is_api_protected(self):
        return True

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

    def is_template_autoescaped(self):
        return True

    ##~~ Helpers

    def _get_connector_params(self) -> Optional[dict]:
        connection_state = self._printer.connection_state
        connector = connection_state.get("connector")
        if connector != "moonraker":
            return None

        host = connection_state.get("host")
        port = connection_state.get("port")
        apikey = connection_state.get("apikey")
        return {"host": host, "port": port, "apikey": apikey}

    def _get_all_webcams(
        self, host: str, port: int, apikey: str = None
    ) -> list[schema.WebcamEntry]:
        webcams = []

        webcams += self._get_moonraker_webcams(host, port, apikey=apikey)
        webcams += self._get_legacy_fluidd_webcams(host, port, apikey=apikey)

        return webcams

    def _get_moonraker_webcams(
        self, host: str, port: int, apikey: str = None
    ) -> list[schema.WebcamEntry]:
        headers = {}
        if apikey:
            headers["X-Api-Key"] = apikey

        r = requests.post(
            URL_WEBCAM_INFO_MOONRAKER.format(host=host, port=port), headers=headers
        )
        data = r.json()

        base = f"http://{host}"
        webcams = []
        for webcam in data.get("webcams", []):
            try:
                entry = schema.WebcamEntry(**webcam)
                entry.snapshot_url = urljoin(base, entry.snapshot_url)
                entry.stream_url = urljoin(base, entry.stream_url)
                webcams.append(entry)
            except ValueError:
                # invalid entry, ignore
                continue
        return webcams

    def _get_legacy_fluidd_webcams(
        self, host: str, port: int, apikey: str = None
    ) -> list[schema.WebcamEntry]:
        headers = {}
        if apikey:
            headers["X-Api-Key"] = apikey

        r = requests.get(
            URL_WEBCAM_INFO_FLUIDD_LEGACY.format(host=host, port=port),
            headers=headers,
        )
        data = r.json()

        if "result" not in data:
            return []

        query_result = data["result"]
        try:
            query_result = schema.FluiddWebcamDatabaseItem(**query_result)
        except ValueError:
            return []

        result = []
        for camera in query_result.value.cameras:
            camera_type = FLUIDD_LEGACY_CAMERA_TYPES.get(camera.type, camera.type)

            try:
                webcam = schema.WebcamEntry(
                    name=camera.name,
                    location="printer",
                    service=camera_type,
                    enabled=True,
                    icon="mdiWebcam",
                    target_fps=camera.fpstarget,
                    target_fps_idle=camera.fpsidletarget,
                    snapshot_url=urljoin(f"http://{host}", camera.url),
                    stream_url=urljoin(f"http://{host}", camera.url),
                    flip_horizontal=camera.flipX,
                    flip_vertical=camera.flipY,
                    rotation=0,
                    aspect_ratio="4:3",
                    extra_data={},
                    source="database",
                    uid=camera.id,
                )
                self._set_mjpegstreamer_urls(webcam)
                result.append(webcam)
            except ValueError:
                # invalid entry, ignore
                continue

        return result

    def _set_mjpegstreamer_urls(self, webcam: schema.WebcamEntry) -> None:
        if webcam.service in MJPEG_STREAMER_WEBCAM_SERVICES:
            webcam.snapshot_url = set_url_query_param(
                webcam.snapshot_url, "action", "snapshot"
            )
            webcam.stream_url = set_url_query_param(webcam.stream_url, "action", "stream")

    def _to_api_webcam(self, webcam: schema.WebcamEntry) -> schema.ApiWebcamEntry:
        return schema.ApiWebcamEntry(
            key=webcam.uid,
            name=webcam.name,
            service=webcam.service,
            enabled=webcam.enabled,
            target_fps=webcam.target_fps,
            target_fps_idle=webcam.target_fps_idle,
            stream_url=webcam.stream_url,
            snapshot_url=webcam.snapshot_url,
            flip_h=webcam.flip_horizontal,
            flip_v=webcam.flip_vertical,
            rotation=webcam.rotation,
            aspect_ratio=webcam.aspect_ratio,
        )


__plugin_name__ = "Moonraker Connector"
__plugin_author__ = "Gina Häußge"
__plugin_description__ = "A printer connector plugin to support communication with Klipper-based printers exposing the Moonraker API"
__plugin_license__ = "AGPLv3"
__plugin_pythoncompat__ = ">=3.9,<4"
__plugin_implementation__ = MoonrakerConnectorPlugin()
