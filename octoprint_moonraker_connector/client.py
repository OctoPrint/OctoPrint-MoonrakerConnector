import enum
import io
import logging
import re
import threading
import time
from collections import namedtuple
from concurrent.futures import Future
from typing import IO, Any, Literal, Optional, Union

import requests

from octoprint.schema import BaseModel, BaseModelExtra

from .jsonrpc import WEBSOCKET_ERROR_CODE_NORMAL, WEBSOCKET_ERROR_CODES, JsonRpcClient


class ThumbnailInfo(BaseModel):
    width: int
    height: int
    size: int
    relative_path: str


class FileInfo(BaseModel):
    path: str
    modified: float
    size: int
    permissions: str


class ExtendedFileInfo(BaseModelExtra):
    filename: str
    modified: float
    size: int
    permissions: str

    estimated_time: Optional[float] = None
    nozzle_diameter: Optional[float] = None
    filament_total: Optional[float] = None
    thumbnails: list[ThumbnailInfo] = []


class InternalFile(ExtendedFileInfo):
    path: str


class DirInfo(BaseModel):
    dirname: str
    modified: float
    size: int
    permissions: str


class DiskUsage(BaseModel):
    free: int
    used: int
    total: int


class JobHistory(BaseModelExtra):
    job_id: str
    user: Optional[str] = None
    filename: str
    exists: bool
    status: str
    start_time: float
    end_time: Optional[float] = None
    print_duration: float
    total_duration: float
    filament_used: float


class PrintStatsSupplemental(BaseModel):
    total_layer: Optional[int] = None
    current_layer: Optional[int] = None


class PrintStats(BaseModel):
    filename: Optional[str] = None

    total_duration: Optional[float] = None
    """Elapsed time since start"""

    print_duration: Optional[float] = None
    """Total duration minus time until first extrusion and pauses, see https://github.com/Klipper3d/klipper/blob/9346ad1914dc50d12f1e5efe630448bf763d1469/klippy/extras/print_stats.py#L112"""

    filament_used: Optional[float] = None

    state: Optional[
        Literal["standby", "printing", "paused", "complete", "error", "cancelled"]
    ] = None

    message: Optional[str] = None

    info: Optional[PrintStatsSupplemental] = None


class SDCardStats(BaseModel):
    file_path: Optional[str] = (
        None  # unset if no file is loaded, path is the path on the file system
    )
    progress: Optional[float] = None  # 0.0 to 1.0
    is_active: Optional[bool] = None  # True if a print is ongoing
    file_position: Optional[int] = None
    file_size: Optional[int] = None


class IdleTimeout(BaseModel):
    state: Optional[Literal["Printing", "Ready", "Idle"]] = (
        None  # "Printing" means some commands are being executed!
    )
    printing_time: Optional[float] = (
        None  # Duration of "Printing" state, resets on state change to "Ready"
    )


Coordinate = namedtuple("Coordinate", "x, y, z, e")


class PositionData(BaseModel):
    speed_factor: Optional[float] = None
    speed: Optional[float] = None
    extruder_factor: Optional[float] = None
    absolute_coordinates: Optional[bool] = None
    absolute_extrude: Optional[bool] = None
    homing_origins: Optional[Coordinate] = None  # offsets
    position: Optional[Coordinate] = None  # current w/ offsets
    gcode_position: Optional[Coordinate] = None  # current w/o offsets


class Configfile(BaseModel):
    config: dict[str, Any] = {}
    settings: dict[str, Any] = {}
    save_config_pending: bool = False
    save_config_pending_items: dict[str, Any] = {}
    warnings: list[str] = []


class TemperatureDataPoint:
    actual: float = 0.0
    target: float = 0.0

    def __init__(self, actual: float = 0.0, target: float = 0.0):
        self.actual = actual
        self.target = target

    def __str__(self):
        return f"{self.actual} / {self.target}"

    def __repr__(self):
        return f"TemperatureDataPoint({self.actual}, {self.target})"


class KlipperState(enum.Enum):
    READY = "ready"
    ERROR = "error"
    SHUTDOWN = "shutdown"
    STARTUP = "startup"
    DISCONNECTED = "disconnected"
    UNKNOWN = "unknown"

    @classmethod
    def for_value(cls, value: str) -> "KlipperState":
        for state in cls:
            if state.value == value:
                return state
        return KlipperState.UNKNOWN


class PrinterState(enum.Enum):
    STANDBY = "standby"
    PRINTING = "printing"
    PAUSED = "paused"
    COMPLETE = "complete"
    ERROR = "error"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"

    @classmethod
    def for_value(cls, value: str) -> "PrinterState":
        for state in cls:
            if state.value == value:
                return state
        return cls.UNKNOWN


class IdleState(enum.Enum):
    PRINTING = "Printing"
    READY = "Ready"
    IDLE = "Idle"
    UNKNOWN = "unknown"

    @classmethod
    def for_value(cls, value: str) -> "IdleState":
        for state in cls:
            if state.value == value:
                return state
        return cls.UNKNOWN


class JobHistoryStatus(enum.Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ERROR = "error"
    KLIPPY_SHUTDONW = "klippy_shutdown"
    KLIPPY_DISCONNECT = "klippy_disconnect"
    INTERRUPTED = "interrupted"
    UNKNOWN = "unknown"

    @classmethod
    def for_value(cls, value: str) -> "KlipperState":
        for state in cls:
            if state.value == value:
                return state
        return JobHistoryStatus.UNKNOWN


class MoonrakerClientListener:
    def on_moonraker_connected(self) -> None:
        pass

    def on_moonraker_disconnected(self, error: str = None) -> None:
        pass

    def on_moonraker_printer_state_changed(self, state: PrinterState) -> None:
        pass

    def on_moonraker_print_progress(
        self,
        progress: Optional[float] = None,
        file_position: Optional[int] = None,
        total_duration: Optional[float] = None,
        print_duration: Optional[float] = None,
    ) -> None:
        pass

    def on_moonraker_print_detected(
        self,
        path: str,
    ) -> None:
        pass

    def on_moonraker_server_info(self, server_info: dict[str, Any]) -> None:
        pass

    def on_moonraker_file_tree_updated(
        self, root: str, path: str, tree: dict[str, dict[str, InternalFile]]
    ) -> None:
        pass

    def on_moonraker_macros_updated(self, macros: list[dict[str, Any]]) -> None:
        pass

    def on_moonraker_temperature_update(
        self, data: dict[str, TemperatureDataPoint]
    ) -> None:
        pass

    def on_moonraker_idle_state(self, state: IdleState) -> None:
        pass

    def on_moonraker_gcode_log(self, *line: str) -> None:
        pass

    def on_moonraker_action_command(
        self, line: str, action: str, params: str = None
    ) -> None:
        pass

    def on_moonraker_position_update(self, position: Coordinate) -> None:
        pass


KLIPPER_STATE_ERROR_LOOKUP = {
    KlipperState.STARTUP: "Klipper is still starting up",
    KlipperState.ERROR: "Klipper experienced an error during startup",
    KlipperState.SHUTDOWN: "Klipper is in a shutdown state",
    KlipperState.DISCONNECTED: "Klipper is not running, has experienced a critical error during startup or doesn't have its API server enabled",
}

MAX_HANDSHAKE_ATTEMPTS = 5

TEMPERATURE_INTERVAL = 1.0

MONITORED_FILE_ROOTS = ("gcodes",)

ACTION_PREFIX = "// action:"

IGNORED_DIRS = (".thumbs",)

MACRO_PARAM_REGEX = re.compile(r"params\.(?P<name>\w+)", flags=re.IGNORECASE)
MACRO_PARAM_DEFAULT_REGEX = re.compile(
    r"\|default\(\s*(?P<value>(?P<quotechar>[\"'])(?:\\(?P=quotechar)|(?!(?P=quotechar)).)*(?P=quotechar)|-?\d[^,\)]*)"
)


class MoonrakerClient(JsonRpcClient):
    WEBSOCKET_URL = "ws://{host}:{port}/websocket"
    HTTP_URL = "http://{host}:{port}"

    GENERIC_HEATER_PREFIX = "heater_generic "
    MACRO_PREFIX = "gcode_macro "

    RELEVANT_PRINTER_OBJECTS = (
        "configfile",
        "display_status",
        "extruder",
        "gcode_move",
        "heater_bed",
        "idle_timeout",
        "print_stats",
        "virtual_sdcard",
        lambda obj_list: [
            x
            for x in obj_list
            if x.startswith(MoonrakerClient.GENERIC_HEATER_PREFIX)
            or x.startswith(MoonrakerClient.MACRO_PREFIX)
        ],
    )

    def __init__(
        self,
        listener: MoonrakerClientListener,
        host: str,
        port: int = 7125,
        apikey: str = None,
        *args,
        **kwargs,
    ):
        super().__init__(self.WEBSOCKET_URL.format(host=host, port=port), *args, **kwargs)

        self._logger = logging.getLogger("octoprint.plugins.moonraker_connector.client")

        self._host = host
        self._port = port
        self._apikey = apikey
        self._listener = listener
        self._connection_id = None

        self._klipper_state: KlipperState = KlipperState.UNKNOWN
        self._klipper_state_subscription = False
        self._subbed_objs: list[str] = []

        self._log_history_received = False

        self._heaters: list[str] = []
        self._current_temperatures: dict[str, TemperatureDataPoint] = {}
        self._last_temperature_update = None

        self._current_tree: dict[str, dict[str, InternalFile]] = {}
        self._current_usage: Optional[DiskUsage] = None

        self._job_history: dict[str, JobHistory] = {}

        self._current_configfile: Configfile = None
        self._current_macros: dict[str, dict[str, Any]] = {}

        self._handshake_attempt = 0

    @property
    def klipper_state(self) -> KlipperState:
        return self._klipper_state

    @klipper_state.setter
    def klipper_state(self, value: KlipperState) -> None:
        if value == self.klipper_state:
            return

        old_state = self.klipper_state

        self._klipper_state = value

        if old_state != KlipperState.READY and value == KlipperState.READY:
            self.attempt_handshake(reset=True)

    @property
    def current_temperatures(self) -> list[TemperatureDataPoint]:
        return self._current_temperatures

    @property
    def current_tree(self) -> dict[str, dict[str, InternalFile]]:
        return self._current_tree

    @property
    def current_usage(self) -> Optional[DiskUsage]:
        return self._current_usage

    @property
    def job_history(self) -> dict[str, JobHistory]:
        return self._job_history

    @property
    def current_macros(self) -> dict[str, dict[str, Any]]:
        return self._current_macros

    def on_open(self, *args, **kwargs):
        try:
            super().on_open(*args, **kwargs)
            self.identify_connection(cb=self.attempt_handshake, cb_kwargs={"reset": True})
        except Exception:
            self._logger.exception("Error in on_open handler")

    def on_close(self, cls, code: int, reason: str):
        try:
            super().on_close(cls, code, reason)
            error = None
            if not self._closing or (code and code != WEBSOCKET_ERROR_CODE_NORMAL):
                if not reason:
                    reason = WEBSOCKET_ERROR_CODES.get(code)

                if reason:
                    error = f"Websocket closed unexpectedly: {reason}"
                else:
                    error = "Websocket closed unexpectedly"
                self._logger.warning(error)

            self._listener.on_moonraker_disconnected(error=error)

        except Exception:
            self._logger.exception("Error in on_close handler")

    def on_error(self, cls, exc: Exception) -> None:
        try:
            super().on_error(cls, exc)
            self._listener.on_moonraker_disconnected(error=str(exc))
        except Exception:
            self._logger.exception("Error in on_error handler")

    def on_message(self, cls, message, *args, **kwargs):
        try:
            super().on_message(cls, message, *args, **kwargs)
        except Exception:
            self._logger.exception("Error in on_message handler")

    ##~~ Initial connection handling

    def identify_connection(
        self, cb=None, cb_args: tuple = None, cb_kwargs: dict[str, Any] = None
    ) -> None:
        from octoprint import __version__ as octoprint_version

        def on_connection_identified(future: Future) -> None:
            try:
                result = future.result()

                self._connection_id = result["connection_id"]
                self._logger.info(
                    f"Connection identified, got connection id {self._connection_id}"
                )

                if callable(cb):
                    nonlocal cb_args, cb_kwargs
                    if cb_args is None:
                        cb_args = ()
                    if cb_kwargs is None:
                        cb_kwargs = {}
                    cb(*cb_args, **cb_kwargs)

            except Exception as exc:
                self._logger.exception("Error while identifying connection")
                error_str = (
                    f"Error while identifying connection: {str(exc)}. API Key correct?"
                )
                self._listener.on_moonraker_disconnected(error=error_str)

        payload = {
            "client_name": "OctoPrint",
            "version": octoprint_version,
            "type": "web",
            "url": "https://octoprint.org",
        }
        if self._apikey:
            payload["api_key"] = self._apikey
        self.call_method("server.connection.identify", params=payload).add_done_callback(
            on_connection_identified
        )

    def attempt_handshake(self, reset=False) -> None:
        if reset:
            self._handshake_attempt = 0

        if not self._klipper_state_subscription:
            # subscribe to the klippy state
            for topic in ("ready", "disconnected", "shutdown"):
                self.add_subscription(
                    f"notify_klippy_{topic}", self.on_klippy_state_change
                )
            self._klipper_state_subscription = True

        self._handshake_attempt += 1
        if self._handshake_attempt > MAX_HANDSHAKE_ATTEMPTS:
            self._listener.on_moonraker_disconnected(
                "Reached maximum connection attempts"
            )
            return

        def on_server_info(future: Future) -> None:
            try:
                server_info = future.result()

                self._klipper_state = KlipperState.for_value(
                    server_info.get("klippy_state", "unknown")
                )

                if self.klipper_state == KlipperState.READY:
                    # proceed with connection
                    self._listener.on_moonraker_server_info(server_info)

                    moonraker_version = server_info.get("moonraker_version")
                    api_version = server_info.get("api_version_string")
                    self._dual_log(
                        logging.INFO,
                        f"Connected to Moonraker {moonraker_version}, API version {api_version}",
                    )

                    self.fetch_console_history()
                    self.fetch_job_history()
                    self.subscribe_to_updates()

                else:
                    # log error
                    error = KLIPPER_STATE_ERROR_LOOKUP.get(self._klipper_state)
                    self._listener.on_moonraker_gcode_log(f"!!! {error}")
                    self._dual_log(logging.ERROR, error)

            except Exception as exc:
                self._logger.exception("Error while retrieving server info")
                error_str = f"Error while retrieving server info: {str(exc)}. Please check moonraker.log for details."
                self._listener.on_moonraker_disconnected(error=error_str)

        self.call_method("server.info").add_done_callback(on_server_info)

    def subscribe_to_updates(self) -> None:
        # subscribe to some status notifications

        self.add_subscription("notify_status_update", self.on_printer_update)
        self.add_subscription("notify_filelist_changed", self.on_filelist_changed)
        self.add_subscription("notify_gcode_response", self.on_gcode_response)

        # and finally subscribe to the printer objects we are interested in

        def on_printer_objects(future: Future) -> None:
            try:
                printer_objects = future.result()

                obj_list = printer_objects.get("objects", [])

                matched_objs = []
                for obj in self.RELEVANT_PRINTER_OBJECTS:
                    if isinstance(obj, str) and obj in obj_list:
                        matched_objs.append(obj)

                    elif callable(obj):
                        matched = obj(obj_list)
                        matched_objs += matched

                if matched_objs:
                    subbed_objs = [
                        obj
                        for obj in matched_objs
                        if obj != "configfile" and not obj.startswith(self.MACRO_PREFIX)
                    ]

                    self._subbed_objs = subbed_objs
                    self._heaters = [
                        obj
                        for obj in matched_objs
                        if obj in ("extruder", "heater_bed")
                        or obj.startswith(self.GENERIC_HEATER_PREFIX)
                    ]

                    self.query_printer_objects(matched_objs)

                    # subscribe to all relevant objects
                    self.subscribe_printer_objects(subbed_objs).add_done_callback(
                        on_printer_objects_subscribed
                    )

            except Exception as exc:
                self._logger.exception("Error while retrieving printer objects")
                error_str = f"Error while retrieving printer objects: {str(exc)}"
                self._listener.on_moonraker_disconnected(error=error_str)

        def on_printer_objects_subscribed(future: Future) -> None:
            try:
                future.result()
                self._listener.on_moonraker_connected()

            except Exception as exc:
                self._logger.exception("Error while subscribing to printer objects")
                error_str = f"Error while subscribing to printer objects: {str(exc)}"
                self._listener.on_moonraker_disconnected(error=error_str)
                return

        self.call_method("printer.objects.list").add_done_callback(on_printer_objects)

    ##~~ Method calls & callbacks

    def query_printer_objects(self, objs: list[str] = None) -> Future:
        if objs is None:
            objs = self._subbed_objs

        def on_result(future: Future) -> None:
            try:
                result = future.result()

                if "status" not in result:
                    self._logger.warning(
                        "Printer object query result is missing expected objects field"
                    )
                    return

                payload = result["status"]
                self._process_query_result(payload)

            except Exception:
                self._logger.exception("Error while querying printer objects")

        params = {"objects": dict.fromkeys(objs)}
        future = self.call_method("printer.objects.query", params=params)
        future.add_done_callback(on_result)
        return future

    def subscribe_printer_objects(self, objs: list[str] = None) -> Future:
        if objs is None:
            objs = self._subbed_objs

        params = {"objects": dict.fromkeys(objs)}
        return self.call_method("printer.objects.subscribe", params=params)

    def query_print_status(self) -> Future[tuple[PrintStats, SDCardStats]]:
        result_future = Future()

        def on_status(future: Future) -> None:
            try:
                result = future.result()
                payload = result.get("status")
                if payload is None:
                    raise ValueError("Response is missing status field")

                if "print_stats" not in payload or "virtual_sdcard" not in payload:
                    raise ValueError(
                        "Response is missing print_stats or virtual_sdcard fields"
                    )

                print_stats = PrintStats(**payload["print_stats"])
                virtual_sdcard = SDCardStats(**payload["virtual_sdcard"])

                result_future.set_result((print_stats, virtual_sdcard))
            except Exception as exc:
                result_future.set_exception(exc)

        self.query_printer_objects(["print_stats", "virtual_sdcard"]).add_done_callback(
            on_status
        )
        return result_future

    def fetch_console_history(self, count: int = 100, force: bool = False) -> Future:
        if self._log_history_received and not force:
            return

        def on_result(future: Future) -> None:
            try:
                result = future.result()

                if "gcode_store" not in result:
                    self._logger.warning(
                        "GCODE store response is missing expected objects field"
                    )
                    return

                lines = []
                for entry in result["gcode_store"]:
                    if "message" not in entry or "type" not in entry:
                        continue

                    if entry["type"] == "command":
                        lines += self._to_multiline_loglines(
                            ">>>", *entry["message"].split("\n")
                        )
                    elif entry["type"] == "response":
                        lines += self._to_multiline_loglines(
                            "<<<", *entry["message"].split("\n")
                        )

                if lines:
                    self._listener.on_moonraker_gcode_log(
                        "--- 8< --- Begin of console history --- 8< ---",
                        *lines,
                        "--- 8< --- End of console history --- 8< ---",
                    )
                self._log_history_received = True

            except Exception:
                self._logger.exception("Error while fetching console history")

        self.call_method("server.gcode_store", params={"count": count}).add_done_callback(
            on_result
        )

    # commands

    def send_gcode_commands(self, *commands: str) -> Future:
        if "M112" in commands:
            return self.trigger_emergency_stop()
        return self.send_gcode_script("\n".join(commands))

    def send_gcode_script(self, script: str) -> Future:
        if not len(script):
            return

        self._listener.on_moonraker_gcode_log(
            *self._to_multiline_loglines(">>>", *script.split("\n"))
        )

        def on_result(future: Future) -> None:
            try:
                result = future.result()
                self._listener.on_moonraker_gcode_log(f"<<< {result}")
            except Exception:
                self._logger.exception("Error while sending GCODE commands to printer")

        future = self.call_method("printer.gcode.script", params={"script": script})
        future.add_done_callback(on_result)
        return future

    def trigger_emergency_stop(self) -> Future:
        self._listener.on_moonraker_gcode_log("--- Triggering an Emergency Stop!")
        return self.call_method("printer.emergency_stop")

    def trigger_host_restart(self) -> Future:
        self._listener.on_moonraker_gcode_log(">>> RESTART")
        return self.call_method("printer.restart")

    def trigger_firmware_restart(self) -> Future:
        self._listener.on_moonraker_gcode_log(">>> FIRMWARE_RESTART")
        return self.call_method("printer.firmware_restart")

    # print job management

    def start_print(self, path: str) -> Future:
        return self.call_method("printer.print.start", params={"filename": path})

    def pause_print(self) -> Future:
        return self.call_method("printer.print.pause")

    def resume_print(self) -> Future:
        return self.call_method("printer.print.resume")

    def cancel_print(self) -> Future:
        return self.call_method("printer.print.cancel")

    # file management

    def _refresh_tree(
        self, root="gcodes", path="", recursive=False, parent: Optional[DirInfo] = None
    ) -> Future:
        refresh_tree_result = Future()

        def on_result(future: Future) -> None:
            try:
                info = future.result()

                prefix = f"{path}/" if path else ""

                self._current_usage = DiskUsage(**info.get("disk_usage"))

                internal_files = [
                    InternalFile(path=f"{prefix}{f['filename']}", **f)
                    for f in info.get("files")
                ]
                self._current_tree[path] = {f.filename: f for f in internal_files}

                if parent:
                    self._current_tree[path]["."] = InternalFile(
                        path=f"{prefix}.",
                        filename=".",
                        modified=parent.modified,
                        size=parent.size,
                        permissions=parent.permissions,
                    )

                dirs = [
                    DirInfo(**d)
                    for d in info.get("dirs")
                    if d["dirname"] not in IGNORED_DIRS
                ]
                if dirs and recursive:
                    futures = [
                        self._refresh_tree(
                            root=root,
                            path=f"{prefix}{d.dirname}",
                            recursive=recursive,
                            parent=d,
                        )
                        for d in dirs
                    ]

                    def fetched(f: Future) -> None:
                        try:
                            f.result()
                            futures.remove(f)
                        except Exception as exc:
                            refresh_tree_result.set_exception(exc)

                        if len(futures) == 0:
                            refresh_tree_result.set_result(self._current_tree)

                    for f in futures:
                        f.add_done_callback(fetched)

                else:
                    refresh_tree_result.set_result(self._current_tree)

            except Exception as exc:
                self._logger.exception(
                    f"Error while fetching directory information for {root}/{path}"
                )
                refresh_tree_result.exception(exc)

        future = self.call_method(
            "server.files.get_directory",
            params={"path": f"{root}/{path}", "extended": True},
        )
        future.add_done_callback(on_result)

        return refresh_tree_result

    def refresh_tree(self, root="gcodes", path="", recursive=False) -> Future:
        def on_result(future: Future) -> None:
            try:
                tree = future.result()
                self._listener.on_moonraker_file_tree_updated(root, path, tree)
            except Exception:
                self._logger.exception(
                    f"Error while fetching file tree for {root}{' and path {path}' if path else ''}"
                )

        future = self._refresh_tree(root=root, path=path, recursive=recursive)
        future.add_done_callback(on_result)
        return future

    def fetch_job_history(self, limit=50, order="desc") -> Future:
        def on_result(future: Future) -> None:
            try:
                history = future.result()
                jobs = [JobHistory(**h) for h in history.get("jobs", [])]
                self._job_history = {job.job_id: job for job in jobs}
            except Exception:
                self._logger.exception(
                    f"Error while fetching job history (limit: {limit})"
                )

        future = self.call_method(
            "server.history.list", params={"limit": limit, "order": order}
        )
        future.add_done_callback(on_result)
        return future

    def upload_file(
        self,
        source: Union[str, IO],
        path: str,
        root: str = "gcodes",
        close_on_eof: bool = True,
        *args,
        **kwargs,
    ) -> Future:
        folder = ""
        filename = path

        future = Future()

        parts = path.split("/")
        if len(parts) > 1:
            folder = "/".join(parts[:-1])
            filename = parts[-1]

        def upload(
            folder: str, filename: str, handle: Union[str, IO], close_on_eof: bool = True
        ):
            try:
                if isinstance(handle, str):
                    close_on_eof = True
                    handle = open(handle, "rb")

                headers = {}
                if self._apikey:
                    headers["X-Api-Key"] = self._apikey

                url = (
                    self.HTTP_URL.format(host=self._host, port=self._port)
                    + "/server/files/upload"
                )

                response = requests.post(
                    url,
                    headers=headers,
                    files={"file": (filename, handle)},
                    data={"root": root, "path": folder},
                )
                response.raise_for_status()

                future.set_result(True)

            except Exception as exc:
                self._logger.exception(f"Error while uploading to {root}/{path}")
                future.set_exception(exc)

            finally:
                if isinstance(handle, io.IOBase) and close_on_eof:
                    handle.close()

        threading.Thread(
            name="Moonraker upload worker",
            target=upload,
            args=(folder, filename, source),
            kwargs={"close_on_eof": close_on_eof},
            daemon=True,
        ).start()
        return future

    def download_file(self, path: str, root: str = "gcodes") -> requests.Response:
        headers = {}
        if self._apikey:
            headers["X-Api-Key"] = self._apikey

        url = (
            self.HTTP_URL.format(host=self._host, port=self._port)
            + f"/server/files/{root}/{path}"
        )

        response = requests.get(url, headers=headers, stream=True)
        response.raise_for_status()

        return response

    def delete_file(self, path: str, root: str = "gcodes") -> Future:
        return self.call_method(
            "server.files.delete_file", params={"path": f"{root}/{path}"}
        )

    def create_folder(self, path: str, root: str = "gcodes") -> Future:
        return self.call_method(
            "server.files.post_directory", params={"path": f"{root}/{path}"}
        )

    def delete_folder(
        self, path: str, root: str = "gcodes", force: bool = False
    ) -> Future:
        return self.call_method(
            "server.files.delete_directory",
            params={"path": f"{root}/{path}", "force": force},
        )

    def move_path(
        self,
        src_path: str,
        dst_path: str,
        src_root: str = "gcodes",
        dst_root: str = "gcodes",
    ) -> Future:
        return self.call_method(
            "server.files.move",
            params={"source": f"{src_root}/{src_path}", "dest": f"{dst_root}/{dst_path}"},
        )

    def copy_path(
        self,
        src_path: str,
        dst_path: str,
        src_root: str = "gcodes",
        dst_root: str = "gcodes",
    ) -> Future:
        return self.call_method(
            "server.files.copy",
            params={"source": f"{src_root}/{src_path}", "dest": f"{dst_root}/{dst_path}"},
        )

    ##~~ Callbacks for notifications

    def on_klippy_state_change(self, notification, params):
        if notification == "notify_klippy_ready":
            self._logger.info("Klippy is ready!")
            self.klipper_state = KlipperState.READY

        elif notification == "notify_klippy_disconnected":
            self._logger.warning("Klipper disconnected!")
            self.klipper_state = KlipperState.DISCONNECTED

        elif notification == "notify_klippy_shutdown":
            self._logger.warning("Klipper shutdown, issue FIRMWARE_RESTART to restart!")
            self.klipper_state = KlipperState.SHUTDOWN

    def on_printer_update(self, _, params):
        payload, _ = params
        self._process_update(payload)

    def on_filelist_changed(self, _, params):
        assert isinstance(params, list)

        to_refresh = []

        def enqueue_refresh(item, target_parent=True) -> None:
            root = item.get("root")
            if root not in MONITORED_FILE_ROOTS:
                return

            path = item.get("path")
            if path is None:
                return

            if target_parent:
                if "/" in path:
                    path, _ = path.rsplit("/", 1)
                else:
                    path = ""

            to_refresh.append((root, path))

        for entry in params:
            action = entry.get("action")
            if action is None:
                continue

            item = entry.get("item")
            if item is None:
                continue

            enqueue_refresh(item, target_parent=(action.endswith("_file")))

            source_item = entry.get("source_item")
            if source_item:
                enqueue_refresh(source_item, target_parent=(action.endswith("_file")))

        for root, path in to_refresh:
            self.refresh_tree(root=root, path=path, recursive=False)

    def on_gcode_response(self, _, params):
        self._listener.on_moonraker_gcode_log(
            *self._to_multiline_loglines("<<<", *params)
        )

        for line in params:
            if line.startswith(ACTION_PREFIX):
                action_command = line[len(ACTION_PREFIX) :].strip()
                if " " in action_command:
                    action_name, action_params = action_command.split(" ", 1)
                    action_name = action_name.strip()
                else:
                    action_name = action_command
                    action_params = ""

                self._listener.on_moonraker_action_command(
                    line, action_name, params=action_params
                )

    ##~~ helpers

    def _process_query_result(self, payload: dict[str, Any]) -> None:
        self._update_gcode_macros(payload)
        self._process_update(payload)

    def _process_update(self, payload: dict[str, Any]) -> None:
        self._update_gcode_move(payload)
        self._update_idle_timeout(payload)
        self._update_print_stats(payload)
        self._update_temperatures(payload)
        self._update_virtual_sdcard(payload)

    def _update_temperatures(self, payload: dict[str, Any]) -> None:
        dirty_actual = False
        dirty_target = False

        for heater in self._heaters:
            if heater not in payload:
                continue

            name = (
                heater[len(self.GENERIC_HEATER_PREFIX) :]
                if heater.startswith(self.GENERIC_HEATER_PREFIX)
                else heater
            )

            data = self._current_temperatures.get(name, TemperatureDataPoint())
            if "temperature" in payload[heater]:
                data.actual = payload[heater]["temperature"]
                dirty_actual = True
            if "target" in payload[heater]:
                data.target = payload[heater]["target"]
                dirty_target = True
            self._current_temperatures[name] = data

        if dirty_actual or dirty_target:
            now = time.monotonic()
            if (
                not dirty_target
                and self._last_temperature_update
                and self._last_temperature_update + TEMPERATURE_INTERVAL > now
            ):
                return

            self._listener.on_moonraker_temperature_update(self._current_temperatures)
            self._last_temperature_update = time.monotonic()

    def _update_print_stats(self, payload: dict[str, Any]) -> None:
        if "print_stats" not in payload:
            return

        print_stats = PrintStats(**payload["print_stats"])

        if print_stats.state is not None:
            printer_state = PrinterState.for_value(print_stats.state)
            self._listener.on_moonraker_printer_state_changed(printer_state)

        if (
            print_stats.total_duration is not None
            or print_stats.print_duration is not None
        ):
            self._listener.on_moonraker_print_progress(
                total_duration=print_stats.total_duration,
                print_duration=print_stats.print_duration,
            )

    def _update_virtual_sdcard(self, payload: dict[str, Any]) -> None:
        if "virtual_sdcard" not in payload:
            return

        sdcard_state = SDCardStats(**payload["virtual_sdcard"])

        if sdcard_state.file_path is not None:
            # this is the very first sd card status we see, before the print starts
            # properly - we'll ignore it for progress calculation to be able to
            # clean long running macros like heat up, leveling etc from the print
            # time estimation
            return

        if sdcard_state.progress is not None or sdcard_state.file_position is not None:
            self._listener.on_moonraker_print_progress(
                progress=sdcard_state.progress, file_position=sdcard_state.file_position
            )

    def _update_idle_timeout(self, payload: dict[str, Any]) -> None:
        if "idle_timeout" not in payload:
            return

        idle_timeout = IdleTimeout(**payload["idle_timeout"])

        if idle_timeout.state is not None:
            state = IdleState.for_value(idle_timeout.state)
            self._listener.on_moonraker_idle_state(state)

    def _update_gcode_move(self, payload: dict[str, Any]) -> None:
        if "gcode_move" not in payload:
            return

        position = PositionData(**payload["gcode_move"])

        if position.gcode_position is not None:
            self._listener.on_moonraker_position_update(position.gcode_position)

    def _update_gcode_macros(self, payload: dict[str, Any]) -> None:
        if "configfile" not in payload:
            return

        macro_keys = [key for key in payload if key.startswith(self.MACRO_PREFIX)]
        if not macro_keys:
            return

        self._current_configfile = Configfile(**payload["configfile"])

        macros = {}

        for key in macro_keys:
            lower_key = key.lower()
            if lower_key not in self._current_configfile.settings:
                continue

            macro = key[len(self.MACRO_PREFIX) :]
            if macro.startswith("_"):
                continue

            gcode = self._current_configfile.settings[lower_key].get("gcode", "")
            macros[macro] = extract_macro_parameters(gcode)

        self._current_macros = macros
        self._listener.on_moonraker_macros_updated(macros)

    def _to_multiline_loglines(self, prefix, *lines) -> list[str]:
        if len(lines) == 0:
            return []
        elif len(lines) == 1:
            return [f"{prefix} {lines[0]}"]
        else:
            return [f"{prefix} {lines[0]}"] + [f"... {line}" for line in lines[1:]]


def extract_macro_parameters(gcode: str) -> dict[str, Union[None, str, int, float, bool]]:
    match = MACRO_PARAM_REGEX.finditer(gcode)
    if not match:
        return {}

    result = {}
    for m in match:
        name = m.group("name")
        value = None

        rest = gcode[m.span(0)[1] :]
        default_match = MACRO_PARAM_DEFAULT_REGEX.match(rest)
        if default_match:
            value = default_match.group("value")

            quotechar = default_match.group("quotechar")
            if quotechar:
                value = value[1:-1].replace(f"\\{quotechar}", quotechar)

        result[name] = value

    return result


if __name__ == "__main__":
    # HOST = "127.0.0.1"
    HOST = "q1pro.lan"

    logging.basicConfig(
        level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    class Listener(MoonrakerClientListener):
        def on_moonraker_temperature_update(self, data):
            for heater, value in data.items():
                print(f"{heater}: {value!s}")
            print("")

    client = MoonrakerClient(HOST, listener=Listener(), daemon=False)
    client.connect()
