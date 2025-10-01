import json
import logging
import threading
from collections import defaultdict
from concurrent.futures import Future
from typing import Any

import websocket


class JsonRpcError(Exception):
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32603
    SERVER_ERROR_RANGE = range(-32000, -32100)

    @classmethod
    def for_error(cls, code: int, message: str, data: Any = None) -> "JsonRpcError":
        if code == cls.PARSE_ERROR:
            error_cls = JsonRpcParseError
        elif code == cls.INVALID_REQUEST:
            error_cls = JsonRpcInvalidRequestError
        elif code == cls.METHOD_NOT_FOUND:
            error_cls = JsonRpcMethodNotFoundError
        elif code == cls.INVALID_PARAMS:
            error_cls = JsonRpcInvalidParamsError
        elif code in cls.SERVER_ERROR_RANGE:
            error_cls = JsonRpcServerError
        else:
            return JsonRpcError(code, message, data=data)

        return error_cls(message, data=data)

    def __init__(self, code, message, data=None):
        super().__init__(message)
        self.code = code
        self.data = data


class JsonRpcParseError(JsonRpcError):
    def __init__(self, message, data=None):
        super().__init__(self.PARSE_ERROR, message, data)


class JsonRpcInvalidRequestError(JsonRpcError):
    def __init__(self, message, data=None):
        super().__init__(self.INVALID_REQUEST, message, data)


class JsonRpcMethodNotFoundError(JsonRpcError):
    def __init__(self, message, data=None):
        super().__init__(self.METHOD_NOT_FOUND, message, data)


class JsonRpcInvalidParamsError(JsonRpcError):
    def __init__(self, message, data=None):
        super().__init__(self.INVALID_PARAMS, message, data)


class JsonRpcServerError(JsonRpcError):
    def __init__(self, message, data=None):
        super().__init__(self.SERVER_ERROR_RANGE[0], message, data)


class JsonRpcClient(websocket.WebSocketApp):
    JSONRPC_VERSION = "2.0"

    def __init__(self, url: str, daemon=True, timeout=30):
        self._daemon = daemon
        self._timeout = timeout

        logger_name = "octoprint.plugins.moonraker_connector.jsonrpc"
        self._logger = logging.getLogger(logger_name)
        self._console_logger = logging.getLogger(f"{logger_name}.console")

        self._connect_future = None

        self._subscribers = defaultdict(list)
        self._calls: dict[int, tuple[str, dict[str, Any], Future]] = {}

        self._msgid_lock = threading.RLock()
        self._msgid_counter = 0

        super().__init__(
            url=url,
            on_open=self.on_open,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
        )

    def connect(self) -> Future:
        self._dual_log(logging.INFO, f"Connecting to {self.url}...")
        self._connect_future = Future()

        self._thread = threading.Thread(
            target=self.connection_thread_runnable,
            name=f"JSONRPC Connection to {self.url}",
        )
        self._thread.daemon = self._daemon
        self._thread.start()

        return self._connect_future

    def connect_sync(self, timeout=None):
        if timeout is None:
            timeout = self._timeout

        self.connect().result(timeout=timeout)

    def connection_thread_runnable(self):
        try:
            self.run_forever()
        except Exception as exc:
            if self._connect_future.running:
                self._connect_future.set_exception(exc)
            self._logger.exception("Exception in connection runner")

    def disconnect(self):
        self.close()

    def on_open(self, cls):
        self._dual_log(logging.INFO, "Connected!")
        self._connect_future.set_result(True)

    def on_message(self, cls, message, *args, **kwargs):
        payload = json.loads(message)
        if isinstance(payload, list):
            for p in payload:
                self._process_message(p)
        elif isinstance(payload, dict):
            self._process_message(payload)

    def _process_message(self, message: dict):
        if message.get("jsonrpc") != self.JSONRPC_VERSION:
            return

        if "result" in message or "error" in message:
            self._process_response(message)

        elif "method" in message:
            method = message["method"]

            if method.startswith("notify_"):
                params = message.get("params")
                self._process_notification(method, params)

            else:
                self.send_error(
                    JsonRpcMethodNotFoundError("Method not found", data=message),
                    msgid=message.get("id"),
                )

    def _process_response(self, response: dict):
        msgid = response.get("id")
        if msgid not in self._calls:
            return

        method, params, future = self._calls.pop(msgid)

        if "result" in response:
            result = response["result"]
            future.set_result(result)
            self._dual_log(
                logging.DEBUG, f"Received result for {method} (id {msgid}): {result!r}"
            )

        elif "error" in response:
            error = response["error"]
            if not isinstance(error, dict):
                pass  # TODO error logging

            code = error["code"]
            message = error["message"]
            data = error.get("data", None)

            exc = JsonRpcError.for_error(code, message, data=data)
            self._dual_log(
                logging.ERROR,
                f"Received error for {method} (id {msgid}): {error!r}",
                exc_info=exc,
            )
            future.set_exception(exc)

    def _process_notification(self, method, params):
        if method in self._subscribers:
            self._console_logger.debug(f"Received notification for {method}: {params!r}")

        for sub in self._subscribers.get(method, []):
            sub(method, params)

    def on_error(self, cls, exc: Exception):
        self._dual_log(logging.ERROR, f"Error: {exc!s}", exc_info=exc)

    def on_close(self, cls, code: int, reason: str):
        self._dual_log(logging.INFO, f"Connection closed: code={code}, reason={reason}")

    def call_method(
        self, method: str, params=None, timeout=None, *args, **kwargs
    ) -> Future:
        if timeout is None:
            timeout = self._timeout

        msgid = self._generate_msgid()

        payload = {"jsonrpc": self.JSONRPC_VERSION, "method": method, "id": msgid}
        if params:
            payload["params"] = params

        self._dual_log(
            logging.DEBUG, f"Calling method {method} (id {msgid}), params: {params!r}"
        )

        def on_done(f: Future) -> None:
            try:
                f.result(timeout=timeout)
            except Exception as exc:
                self._dual_log(
                    logging.DEBUG, f"Error calling method {method}", exc_info=exc
                )
                raise exc

        future = Future()
        future.add_done_callback(on_done)

        self._calls[msgid] = (method, params, future)
        self.send_text(json.dumps(payload))

        return future

    def send_error(self, error: JsonRpcError, msgid: Any = None):
        payload = {
            "jsonrpc": self.JSONRPC_VERSION,
            "error": {
                "code": error.code,
                "message": str(error),
            },
        }
        if error.data:
            payload["error"]["data"] = error.data
        if msgid:
            payload["id"] = msgid

        self.send_text(json.dumps(payload))

    def add_subscription(self, notification, callback):
        if callback not in self._subscribers[notification]:
            self._subscribers[notification].append(callback)

    def remove_subscription(self, notification, callback):
        try:
            self._subscribers[notification].remove(callback)
        except ValueError:
            pass

    def reset_subscriptions(self):
        self._subscribers.clear()

    def _generate_msgid(self):
        with self._msgid_lock:
            self._msgid_counter += 1
            return self._msgid_counter

    def _dual_log(self, level, *args, **kwargs):
        self._logger.log(level, *args, **kwargs)
        self._console_logger.log(level, *args, **kwargs)
