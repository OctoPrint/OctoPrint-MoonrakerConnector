from typing import Any, Union

from octoprint.schema import BaseModel


class ApiWebcamEntry(BaseModel):
    key: str
    name: str
    service: str
    enabled: bool
    target_fps: int
    target_fps_idle: int
    stream_url: str
    snapshot_url: str
    flip_h: bool
    flip_v: bool
    rotation: int
    aspect_ratio: str


class ApiResponse(BaseModel):
    webcams: list[ApiWebcamEntry] = []


class WebcamEntry(BaseModel):
    name: str
    location: str
    service: str
    enabled: bool
    icon: str
    target_fps: int
    target_fps_idle: int
    stream_url: str
    snapshot_url: str
    flip_horizontal: bool
    flip_vertical: bool
    rotation: int
    aspect_ratio: str
    extra_data: dict
    source: str
    uid: str


class DatabaseItem(BaseModel):
    namespace: str
    key: Union[str, list[str], None]
    value: Any


class FluiddWebcamEntry(BaseModel):
    id: str
    enabled: bool
    name: str
    type: str
    fpstarget: int
    fpsidletarget: int
    url: str
    flipX: bool
    flipY: bool
    height: int


class FluiddWebcamDatabaseValue(BaseModel):
    cameras: list[FluiddWebcamEntry]


class FluiddWebcamDatabaseItem(DatabaseItem):
    value: FluiddWebcamDatabaseValue
