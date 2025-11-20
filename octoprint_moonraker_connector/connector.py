import datetime
import logging
import math
import os
from concurrent.futures import Future
from email.utils import parsedate_to_datetime
from typing import IO, TYPE_CHECKING, Any, Optional, Union, cast

from octoprint.events import Events
from octoprint.filemanager import FileDestinations, valid_file_type
from octoprint.filemanager.storage import (
    AnalysisFilamentUse,
    AnalysisResult,
    MetadataEntry,
    StorageCapabilities,
    StorageThumbnail,
)
from octoprint.printer import JobProgress, PrinterFile, PrinterFilesMixin
from octoprint.printer.connection import (
    ConnectedPrinter,
    ConnectedPrinterState,
    FirmwareInformation,
)
from octoprint.printer.job import PrintJob
from octoprint.schema.config.controls import (
    CustomControl,
    CustomControlContainer,
    CustomControlInput,
)
from octoprint.util.tz import UTC_TZ

from .client import (
    Coordinate,
    IdleState,
    InternalFile,
    KlipperState,
    MoonrakerClient,
    MoonrakerClientListener,
    PrinterState,
    PrintStats,
    SDCardStats,
    TemperatureDataPoint,
    ThumbnailInfo,
)

if TYPE_CHECKING:
    from octoprint.events import EventManager
    from octoprint.filemanager import FileManager
    from octoprint.plugin import PluginManager, PluginSettings


EXTENSION_TO_THUMBNAIL_MIME = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "bmp": "image/bmp",
}


class ConnectedMoonrakerPrinter(
    ConnectedPrinter, PrinterFilesMixin, MoonrakerClientListener
):
    connector = "moonraker"
    name = "Klipper (Moonraker)"

    # injected by our plugin
    _event_bus: "EventManager" = None
    _file_manager: "FileManager" = None
    _plugin_manager: "PluginManager" = None
    _plugin_settings: "PluginSettings" = None
    # /injected

    storage_capabilities = StorageCapabilities(
        write_file=True,
        read_file=True,
        remove_file=True,
        copy_file=True,
        move_file=True,
        add_folder=True,
        remove_folder=True,
        copy_folder=True,
        move_folder=True,
        metadata=True,
        thumbnails=True,
    )

    supports_job_on_hold = False
    supports_temperature_offsets = False

    @classmethod
    def connection_options(cls) -> dict:
        return {}

    @classmethod
    def connection_preconditions_met(cls, params):
        from octoprint.util.net import resolve_host

        host = params.get("host")
        return host and resolve_host(host)

    TEMPERATURE_LOOKUP = {"extruder": "tool0", "heater_bed": "bed", "chamber": "chamber"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._logger = logging.getLogger(__name__)

        self._host = kwargs.get("host")

        try:
            self._port = int(kwargs.get("port"))
        except ValueError:
            self._port = 7125
        self._apikey = kwargs.get("apikey")

        self._client = None

        self._state = ConnectedPrinterState.CLOSED
        self._error = None

        self._progress: JobProgress = None
        self._job_cache: list[str] = []
        self._job_delay: float = 0.0

        self._printer_state: PrinterState = IdleState.UNKNOWN
        self._idle_state: IdleState = IdleState.UNKNOWN
        self._position: Coordinate = None

    @property
    def connection_parameters(self):
        parameters = super().connection_parameters
        parameters.update(
            {"host": self._host, "port": self._port, "apikey": self._apikey}
        )
        return parameters

    def set_state(self, state: ConnectedPrinterState, error: str = None):
        if state == self.state:
            return

        old_state = self.state

        super().set_state(state, error=error)

        message = f"State changed from {old_state.name} to {self.state.name}"
        self._logger.info(message)
        self._listener.on_printer_logs(message)

    @property
    def job_progress(self) -> JobProgress:
        return self._progress

    def connect(self, *args, **kwargs):
        from . import MoonrakerJsonRpcLogHandler

        if self._client is not None:
            return

        MoonrakerJsonRpcLogHandler.arm_rollover()

        self.state = ConnectedPrinterState.CONNECTING
        self._client = MoonrakerClient(
            self, self._host, port=self._port, apikey=self._apikey
        )
        self._client.connect()

    def disconnect(self, *args, **kwargs):
        if self._client is None:
            return
        self._event_bus.fire(Events.DISCONNECTING)
        self._client.disconnect()

    def emergency_stop(self, *args, **kwargs):
        self.commands("M112", tags=kwargs.get("tags", set()))

    def get_error(self, *args, **kwargs):
        return self._error

    def get_additional_controls(
        self,
    ) -> list[Union[CustomControl, CustomControlContainer]]:
        controls = [
            self._to_custom_control(macro, data)
            for macro, data in self._client.current_macros.items()
        ]
        controls.sort(key=lambda x: x.name.lower())

        return [
            CustomControlContainer(
                name=f"Printer Macros ({len(controls)})",
                children=controls,
                collapsed=True,
            )
        ]

    def jog(self, axes, relative=True, speed=None, *args, **kwargs):
        command = "G0 {}".format(
            " ".join([f"{axis.upper()}{amt}" for axis, amt in axes.items()])
        )

        if speed is None:
            speed = min(self._profile["axes"][axis]["speed"] for axis in axes)

        if speed and not isinstance(speed, bool):
            command += f" F{speed}"

        if relative:
            commands = ["G91", command, "G90"]
        else:
            commands = ["G90", command]

        self.commands(
            *commands, tags=kwargs.get("tags", set()) | {"trigger:connector.jog"}
        )

    def home(self, axes, *args, **kwargs):
        self.commands(
            "G91",
            "G28 {}".format(" ".join(f"{x.upper()}0" for x in axes)),
            "G90",
            tags=kwargs.get("tags", set) | {"trigger:connector.home"},
        )

    def extrude(self, amount, speed=None, *args, **kwargs):
        # Use specified speed (if any)
        max_e_speed = self._profile["axes"]["e"]["speed"]

        if speed is None:
            # No speed was specified so default to value configured in printer profile
            extrusion_speed = max_e_speed
        else:
            # Make sure that specified value is not greater than maximum as defined in printer profile
            extrusion_speed = min([speed, max_e_speed])

        self.commands(
            "G91",
            "M83",
            f"G1 E{amount} F{extrusion_speed}",
            "M82",
            "G90",
            tags=kwargs.get("tags", set()) | {"trigger:connector.extrude"},
        )

    def change_tool(self, tool, *args, **kwargs):
        tool = int(tool[len("tool") :])
        self.commands(
            f"T{tool}",
            tags=kwargs.get("tags", set()) | {"trigger:connector.change_tool"},
        )

    def set_temperature(self, heater, value, tags=None, *args, **kwargs):
        if not tags:
            tags = set()
        tags |= {"trigger:connector.set_temperature"}

        if heater == "tool":
            # set current tool, whatever that might be
            self.commands(f"M104 S{value}", tags=tags)

        elif heater.startswith("tool"):
            # set specific tool
            extruder_count = self._profile["extruder"]["count"]
            shared_nozzle = self._profile["extruder"]["sharedNozzle"]
            if extruder_count > 1 and not shared_nozzle:
                toolNum = int(heater[len("tool") :])
                self.commands(f"M104 T{toolNum} S{value}", tags=tags)
            else:
                self.commands(f"M104 S{value}", tags=tags)

        elif heater == "bed":
            self.commands(f"M140 S{value}", tags=tags)

        elif heater == "chamber":
            self.commands(f"M141 S{value}", tags=tags)

    def commands(self, *commands, tags=None, force=False, **kwargs):
        if self._client is None:
            return

        self._client.send_gcode_commands(*commands)

    def is_ready(self, *args, **kwargs):
        return (
            super().is_ready(*args, **kwargs)
            and self._client.klipper_state == KlipperState.READY
        )

    ##~~ Job handling

    def supports_job(self, job: PrintJob) -> bool:
        if not valid_file_type(job.path, type="machinecode"):
            return False

        if (
            job.storage != FileDestinations.PRINTER
            and not self._file_manager.capabilities(job.storage).read_file
        ):
            return False

        return True

    def start_print(self, pos=None, user=None, tags=None, *args, **kwargs):
        if pos is None:
            pos = 0

        self.state = ConnectedPrinterState.STARTING
        self._progress = JobProgress(
            job=self.current_job, progress=0.0, pos=pos, elapsed=0.0, cleaned_elapsed=0.0
        )
        self._job_delay = 0.0

        try:
            if self.current_job.storage == FileDestinations.PRINTER:
                self._client.start_print(self.current_job.path).result()

            else:
                # we first need to upload this as a cache file, then start the print on that

                if self._job_cache:
                    # if we still have a job cache file, delete it now
                    for f in self._job_cache:
                        self._client.delete_file(f)
                    self._job_cache = []

                _, filename = self._file_manager.split_path(
                    self.current_job.storage, self.current_job.path
                )
                job_cache = f".octoprint/{filename}"
                print_future = Future()

                def handle_uploaded(future: Future) -> None:
                    try:
                        future.result()

                        self._client.start_print(job_cache).result()

                        print_future.set_result(True)

                    except Exception as exc:
                        print_future.set_exception(exc)

                handle = self._file_manager.read_file(
                    self.current_job.storage, self.current_job.path
                )
                self._client.upload_file(handle, job_cache).add_done_callback(
                    handle_uploaded
                )
                print_future.result()

        except Exception:
            self._logger.exception(
                f"Error while starting print job of {self.current_job.storage}:{self.current_job.path}"
            )
            self._listener.on_printer_job_cancelled()
            self.state = ConnectedPrinterState.OPERATIONAL

    def pause_print(self, tags=None, *args, **kwargs):
        self.state = ConnectedPrinterState.PAUSING
        self._client.pause_print().result()

    def resume_print(self, tags=None, *args, **kwargs):
        self.state = ConnectedPrinterState.RESUMING
        self._client.resume_print().result()

    def cancel_print(self, tags=None, *args, **kwargs):
        self.state = ConnectedPrinterState.CANCELLING
        if self._plugin_settings.get_boolean(["emergency_stop_on_cancel"]):
            self._client.trigger_emergency_stop().result()
            self._client.send_gcode_commands("FIRMWARE_RESTART")
        else:
            self._client.cancel_print().result()

    ##~~ PrinterFilesMixin

    @property
    def printer_files_mounted(self) -> bool:
        return self._client is not None

    def refresh_printer_files(
        self, path="", recursive=False, blocking=False, timeout=10, *args, **kwargs
    ) -> None:
        future = self._client.refresh_tree(path=path, recursive=recursive)
        if blocking:
            future.result(timeout=timeout)

    def get_printer_files(self, refresh=False, recursive=False, *args, **kwargs):
        if not self.printer_files_mounted:
            return []

        if refresh:
            self.refresh_printer_files(recursive=recursive, blocking=True)

        result = []
        for contents in self._client.current_tree.values():
            children = [self._to_printer_file(f) for f in contents.values()]
            result.extend(children)
        return result

    def _get_internal_file(self, path: str, refresh=False) -> Optional[InternalFile]:
        if not self.printer_files_mounted:
            return None

        if "/" in path:
            parent, name = path.rsplit("/", 1)
        else:
            parent = ""
            name = path

        if refresh:
            self.refresh_printer_files(path=parent, blocking=True)

        if (
            parent in self._client.current_tree
            and name in self._client.current_tree[parent]
        ):
            return self._client.current_tree[parent][name]

        return None

    def get_printer_file(self, path: str, refresh=False, *args, **kwargs):
        internal = self._get_internal_file(path, refresh=refresh)
        if not internal:
            return None
        return self._to_printer_file(internal)

    def create_printer_folder(self, target: str, *args, **kwargs) -> str:
        self._client.create_folder(target).result()
        return target

    def delete_printer_folder(
        self, target: str, recursive: bool = False, *args, **kwargs
    ) -> None:
        self._client.delete_folder(target, force=recursive).result()

    def copy_printer_folder(self, source, target, *args, **kwargs) -> str:
        self._client.copy_path(source, target).result()
        return target

    def move_printer_folder(self, source, target, *args, **kwargs) -> str:
        self._client.move_path(source, target).result()
        return target

    def upload_printer_file(
        self, path_or_file, path, upload_callback, *args, **kwargs
    ) -> str:
        def on_upload_done(future: Future) -> None:
            try:
                future.result()
                if callable(upload_callback):
                    upload_callback(done=True)
            except Exception:
                if callable(upload_callback):
                    upload_callback(failed=True)
                self._logger.exception(f"Uploading to {path} failed")

        self._client.upload_file(path_or_file, path).add_done_callback(on_upload_done)
        return path

    def download_printer_file(self, path, *args, **kwargs) -> IO:
        return self._client.download_file(path).raw

    def delete_printer_file(self, path, *args, **kwargs) -> None:
        self._client.delete_file(path).result()

    def copy_printer_file(self, source, target, *args, **kwargs) -> str:
        self._client.copy_path(source, target).result()
        return target

    def move_printer_file(self, source, target, *args, **kwargs) -> str:
        self._client.move_path(source, target).result()
        return target

    def get_printer_file_metadata(self, path, *args, **kwargs) -> MetadataEntry:
        internal = self._get_internal_file(path)
        if not internal:
            return None

        return self._get_metadata_entry_for_file(internal)

    def has_thumbnail(self, path, *args, **kwargs):
        internal = self._get_internal_file(path)
        return internal and internal.thumbnails

    def get_thumbnail(
        self, path, sizehint=None, *args, **kwargs
    ) -> Optional[StorageThumbnail]:
        thumbnail = self._thumbnail_for_sizehint(path, sizehint=sizehint)
        if not thumbnail:
            return None

        return self._to_storage_thumbnail(thumbnail, path)

    def download_thumbnail(self, path, sizehint=None, *args, **kwargs) -> Optional[IO]:
        thumbnail = self._thumbnail_for_sizehint(path, sizehint=sizehint)
        if not thumbnail:
            return None

        meta = self._to_storage_thumbnail(thumbnail, path)

        thumb_path = thumbnail.relative_path

        if "/" in path:
            folder = path.rsplit("/", maxsplit=1)[0]
            response = self._client.download_file(f"{folder}/{thumb_path}")
        else:
            response = self._client.download_file(thumb_path)

        if "Content-Type" in response.headers:
            meta.mime = response.headers.get("Content-Type")
        if "Content-Length" in response.headers:
            meta.size = int(response.headers.get("Content-Length"))
        if "Last-Modified" in response.headers:
            lm = parsedate_to_datetime(response.headers.get("Last-Modified"))
            meta.last_modified = int(lm.timestamp())

        return meta, response.raw

    def _to_storage_thumbnail(
        self, thumbnail: ThumbnailInfo, printable: str
    ) -> StorageThumbnail:
        name = thumbnail.relative_path
        if "/" in name:
            name = name.rsplit("/", maxsplit=1)[1]

        ext = thumbnail.relative_path.rsplit(".", maxsplit=1)[1]

        return StorageThumbnail(
            name=name,
            printable=printable,
            sizehint=f"{thumbnail.width}x{thumbnail.height}",
            mime=EXTENSION_TO_THUMBNAIL_MIME.get(ext, "image/png"),
            size=thumbnail.size,
        )

    def _thumbnail_for_sizehint(self, path, sizehint=None) -> Optional[ThumbnailInfo]:
        internal = self._get_internal_file(path)
        if not internal or not internal.thumbnails:
            return None

        sorted_thumbnails = sorted(
            internal.thumbnails, key=lambda x: x.width * x.height, reverse=True
        )
        if sizehint:
            w, h = map(int, sizehint.split("x"))
            for t in sorted_thumbnails:
                if t.width == w and t.height == h:
                    return t
        return sorted_thumbnails[0]

    ##~~ MoonrakerClientListener interface

    def on_moonraker_connected(self):
        self.state = ConnectedPrinterState.OPERATIONAL
        self._event_bus.fire(
            Events.CONNECTED,
            {
                "connector": self.name,
                "host": self._host,
                "port": self._port,
                "apikey": self._apikey is not None,
            },
        )
        self._listener.on_printer_files_available(True)
        self.refresh_printer_files(recursive=True)

    def on_moonraker_disconnected(self, error: str = None):
        self._listener.on_printer_files_available(False)
        if error:
            self._error = error
            self.set_state(ConnectedPrinterState.CLOSED_WITH_ERROR, error=error)
        else:
            self.state = ConnectedPrinterState.CLOSED
        self._event_bus.fire(Events.DISCONNECTED)

    def on_moonraker_server_info(self, server_info):
        firmware_info = FirmwareInformation(
            name="Klipper",
            data={
                "moonraker_version": server_info.get("moonraker_version", "unknown"),
                "api_version": server_info.get("api_version_string", "0.0.0"),
            },
        )
        self._listener.on_printer_firmware_info(firmware_info)

    def on_moonraker_temperature_update(
        self, data: dict[str, TemperatureDataPoint]
    ) -> None:
        self._listener.on_printer_temperature_update(
            {
                self.TEMPERATURE_LOOKUP.get(key): (value.actual, value.target)
                for key, value in data.items()
            }
        )

    def on_moonraker_gcode_log(self, *lines: str) -> None:
        self._listener.on_printer_logs(*lines)

    def on_moonraker_file_tree_updated(
        self, root: str, path: str, tree: dict[str, dict[str, InternalFile]]
    ):
        if root != "gcodes":
            return

        paths = [
            p
            for p in self._client.current_tree
            if p == ".octoprint" or p.startswith(".octoprint/")
        ]
        job_cache = []
        for p in paths:
            job_cache.extend([f.path for f in self._client.current_tree[p].values()])
        self._job_cache = job_cache

        self._listener.on_printer_files_refreshed(self.get_printer_files(refresh=False))

    def on_moonraker_macros_updated(self, macros):
        self._listener.on_printer_controls_updated(self.get_additional_controls())

    def on_moonraker_printer_state_changed(self, state: PrinterState) -> None:
        self._printer_state = state

        if state == PrinterState.PRINTING:
            if self.state not in (
                ConnectedPrinterState.STARTING,
                ConnectedPrinterState.PAUSING,
                ConnectedPrinterState.PAUSED,
                ConnectedPrinterState.RESUMING,
                ConnectedPrinterState.PRINTING,
            ):
                # externally triggered print job, let's see what's being printed
                def on_status(future: Future[tuple[PrintStats, SDCardStats]]) -> None:
                    try:
                        print_stats, virtual_sdcard = cast(
                            tuple[PrintStats, SDCardStats], future.result()
                        )

                        path = print_stats.filename
                        size = virtual_sdcard.file_size

                        if path is None or size is None:
                            raise ValueError("Missing path or size")

                        job = self.create_job(path)

                    except Exception:
                        self._logger.exception(
                            "Error while querying status, setting unknown job"
                        )

                        job = PrintJob(storage="printer", path="???", display="???")

                    self.set_job(job)
                    self._listener.on_printer_job_changed(job)

                    self.state = ConnectedPrinterState.PRINTING

                self._client.query_print_status().add_done_callback(on_status)

            elif self.state != ConnectedPrinterState.PRINTING:
                if self.state in (
                    ConnectedPrinterState.PAUSING,
                    ConnectedPrinterState.PAUSED,
                ):
                    self.state = ConnectedPrinterState.RESUMING
                self._evaluate_actual_status()

        elif state == PrinterState.PAUSED:
            self._evaluate_actual_status()

        elif state in (
            PrinterState.COMPLETE,
            PrinterState.CANCELLED,
            PrinterState.ERROR,
        ):
            if state == PrinterState.COMPLETE:
                self.state = ConnectedPrinterState.FINISHING
            else:
                self.state = ConnectedPrinterState.CANCELLING
            self._evaluate_actual_status()

        elif state == PrinterState.STANDBY:
            self._evaluate_actual_status()

    def on_moonraker_print_progress(
        self,
        progress: float = None,
        file_position: int = None,
        total_duration: float = None,
        print_duration: float = None,
    ):
        if self._progress is None and self.current_job is not None:
            self._progress = JobProgress(
                job=self.current_job,
                progress=0.0,
                pos=0,
                elapsed=0.0,
                cleaned_elapsed=0.0,
            )
            self._job_delay = 0.0

        if self._progress is None:
            return

        dirty = False

        if progress is not None:
            self._progress.progress = progress
            dirty = True
        if file_position is not None:
            self._progress.pos = file_position
            dirty = True
        if print_duration is not None:
            self._progress.elapsed = print_duration
            if self._progress.progress:
                if not self._job_delay:
                    self._job_delay = print_duration
                self._progress.cleaned_elapsed = print_duration - self._job_delay
            else:
                self._progress.cleaned_elapsed = 0.0

            if self.current_job.duration_estimate:
                self._progress.left_estimate = (
                    self.current_job.duration_estimate.estimate
                    - self._progress.cleaned_elapsed
                )

            dirty = True

        if dirty:
            self._listener.on_printer_job_progress()

    def on_moonraker_idle_state(self, state: IdleState):
        self._idle_state = state
        self._evaluate_actual_status()

    def on_moonraker_action_command(
        self, line: str, action: str, params: str = None
    ) -> None:
        if action == "start":
            if self.get_current_job():
                self.start_print()

        elif action == "cancel":
            self.cancel_print()

        elif action == "pause":
            self.pause_print()

        elif action == "paused":
            # already handled differently
            pass

        elif action == "resume":
            self.resume_print()

        elif action == "resumed":
            # already handled differently
            pass

        elif action == "disconnect":
            self.disconnect()

        elif action in ("sd_inserted", "sd_updated"):
            self.refresh_printer_files()

        elif action == "shutdown":
            if self._plugin_settings.global_get_boolean(
                ["serial", "enableShutdownActionCommand"]
            ):
                from octoprint.server import system_command_manager

                try:
                    system_command_manager.perform_system_shutdown()
                except Exception as ex:
                    self._logger.error(f"Error executing system shutdown: {ex}")
            else:
                self._logger.warning(
                    "Received a shutdown command from the printer, but processing of this command is disabled"
                )

        action_command = action + f" {params}" if params else ""
        for name, hook in self._plugin_manager.get_hooks(
            "octoprint.comm.protocol.action"
        ).items():
            try:
                hook(self, line, action_command, name=action, params=params)
            except Exception:
                self._logger.exception(
                    f"Error while calling hook from plugin {name} with action command {action_command}",
                    extra={"plugin": name},
                )

    def on_moonraker_position_update(self, position: Coordinate):
        prev = self._position
        if prev and prev.z != position.z:
            self._event_bus.fire(Events.Z_CHANGE, {"new": position.z, "old": prev.z})
        self._position = position

    ##~~ helpers

    def _evaluate_actual_status(self):
        if self.state in (
            ConnectedPrinterState.STARTING,
            ConnectedPrinterState.RESUMING,
        ):
            if self._printer_state != PrinterState.PRINTING:
                # not yet printing
                return

            if self.state == ConnectedPrinterState.STARTING:
                self._listener.on_printer_job_started()
            else:
                self._listener.on_printer_job_resumed()
            self.state = ConnectedPrinterState.PRINTING

        elif self.state in (
            ConnectedPrinterState.FINISHING,
            ConnectedPrinterState.CANCELLING,
            ConnectedPrinterState.PAUSING,
        ):
            if self._idle_state == IdleState.PRINTING:
                # still printing
                return

            if self.state == ConnectedPrinterState.FINISHING and self._printer_state in (
                PrinterState.COMPLETE,
                PrinterState.STANDBY,
            ):
                # print done
                self._progress.progress = 1.0
                self._listener.on_printer_job_done()
                self.state = ConnectedPrinterState.OPERATIONAL
            elif (
                self.state == ConnectedPrinterState.CANCELLING
                and self._printer_state
                in (PrinterState.CANCELLED, PrinterState.ERROR, PrinterState.STANDBY)
            ):
                # print failed
                self._listener.on_printer_job_cancelled()
                self.state = ConnectedPrinterState.OPERATIONAL
            elif (
                self.state == ConnectedPrinterState.PAUSING
                and self._printer_state == PrinterState.PAUSED
            ):
                # print paused
                self._listener.on_printer_job_paused()
                self.state = ConnectedPrinterState.PAUSED

    def _get_metadata_entry_for_file(self, f: InternalFile) -> MetadataEntry:
        filament_length = f.filament_total
        nozzle_dia = f.nozzle_diameter

        filament_analysis = {}
        if filament_length and nozzle_dia:
            radius = nozzle_dia / 2.0
            filament_volume = math.pi * radius * radius * filament_length / 1000.0
            filament_analysis = {
                "tool0": AnalysisFilamentUse(
                    length=filament_length, volume=filament_volume
                )
            }

        return MetadataEntry(
            display=os.path.basename(f.path),
            analysis=AnalysisResult(
                estimatedPrintTime=f.estimated_time,
                filament=filament_analysis,
            ),
        )

    def _to_printer_file(self, internal: InternalFile) -> PrinterFile:
        if internal.filename == ".":
            # folder metadata
            path = internal.path[:-1]
            return PrinterFile(
                path=path,
                display=path.rsplit("/")[-2] if "/" in path else path,
                size=internal.size,
                date=datetime.datetime.fromtimestamp(internal.modified, tz=UTC_TZ),
            )

        display = internal.path
        if "/" in internal.path:
            _, display = internal.path.rsplit("/", 1)

        thumbnails = []
        if internal.thumbnails:
            thumbnails = [f"{x.width}x{x.height}" for x in internal.thumbnails]

        return PrinterFile(
            path=internal.path,
            display=display,
            size=internal.size,
            date=datetime.datetime.fromtimestamp(internal.modified, tz=UTC_TZ),
            metadata=self._get_metadata_entry_for_file(internal),
            thumbnails=thumbnails,
        )

    def _to_custom_control(self, macro: str, data: dict[str, Any]) -> CustomControl:
        if data:
            inputs = [
                CustomControlInput(
                    name=name, parameter=name, default=value if value is not None else ""
                )
                for name, value in data.items()
            ]
            return CustomControl(
                name=macro,
                command=macro
                + " "
                + " ".join([f"{input.name}={{{input.name}}}" for input in inputs]),
                input=inputs,
            )
        else:
            return CustomControl(name=macro, command=macro)
