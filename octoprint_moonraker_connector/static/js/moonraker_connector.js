$(function () {
    function MoonrakerConnectorViewModel(parameters) {
        const self = this;

        self.loginState = parameters[0];
        self.access = parameters[1];
        self.settingsViewModel = parameters[2];
        self.printerState = parameters[3];

        self.btnRestartClick = function() {
            OctoPrint.control.sendGcode('RESTART');
        }

        self.btnFirmwareRestartClick = function() {
            OctoPrint.control.sendGcode('FIRMWARE_RESTART');
        }

        self.initializeButton = function() {
            var buttonContainer = $('#job_print')[0].parentElement;
            var container = document.createElement("div");
            container.classList.add("row-fluid", "print-control");
            container.style.marginTop = "10px";
            container.setAttribute("data-bind", "visible: $root.loginState.hasPermissionKo($root.access.permissions.PRINT)");

            var btnRestart = document.createElement("button");
            btnRestart.id = "job_restart";
            btnRestart.title = "Reload configuration file and performs an internal reset of the host software. It does not clear the error state from the micro-controller.";
            btnRestart.classList.add("btn");
            btnRestart.classList.add("span6");
            btnRestart.addEventListener("click", self.btnRestartClick);

            var btnRestartIcon = document.createElement("i");
            btnRestartIcon.classList.add("fa", "fa-redo");
            btnRestart.appendChild(btnRestartIcon);

            var btnRestartText = document.createElement("span");
            btnRestartText.textContent = " Restart";
            btnRestart.appendChild(btnRestartText);

            container.appendChild(btnRestart);

            var btnFirmwareRestart = document.createElement("button");
            btnFirmwareRestart.id = "job_firmware_restart";
            btnFirmwareRestart.title = "Reload configuration file and performs an internal reset of the host software, but it also clears any error states from the micro-controller.";
            btnFirmwareRestart.classList.add("btn");
            btnFirmwareRestart.classList.add("span6");
            btnFirmwareRestart.addEventListener("click", self.btnFirmwareRestartClick);

            var btnFirmwareRestartIcon = document.createElement("i");
            btnFirmwareRestartIcon.classList.add("fa", "fa-sync");
            btnFirmwareRestart.appendChild(btnFirmwareRestartIcon);

            var btnFirmwareRestartText = document.createElement("span");
            btnFirmwareRestartText.textContent = " Firmware Restart";
            btnFirmwareRestart.appendChild(btnFirmwareRestartText);
            
            container.appendChild(btnFirmwareRestart);

            buttonContainer.after(container);
        };

        self.webcams = ko.observableArray([]);
        self.webcamAvailable = ko.pureComputed(() => {
            return self.webcams().length > 0;
        });
        self.cameraVisible = ko.observable(false);

        self.requestData = function () {
            return OctoPrint.plugins.moonraker_connector.get().done(self.fromResponse);
        };

        self.fromResponse = function (response) {
            const webcams = response.webcams.filter((webcam) => webcam.enabled);
            if (webcams.length === 0) {
                self.webcams([]);
                return;
            }

            const webcam = webcams[0]; // only the first visible one is supported for now
            const cam = {
                ...webcam,
                template: () => {
                    return `moonraker_connector_webcam_template_${webcam.service}`;
                },
                cacheBuster: ko.observable(),
                url: ko.pureComputed(() => {
                    let url;
                    switch (webcam.service) {
                        case "mjpegstreamer":
                            url = webcam.stream_url;
                            break;
                        case "mjpegstreamer-adaptive":
                            url = webcam.snapshot_url;
                            break;
                    }

                    const cacheBuster = cam.cacheBuster();
                    if (url.indexOf("?") !== -1) {
                        return `${url}&_=${cacheBuster}`;
                    } else {
                        return `${url}?_=${cacheBuster}`;
                    }
                }),
                activeFpsTarget: ko.pureComputed(() => {
                    if (!webcam.target_fps || !webcam.target_fps_idle) return 0;

                    if (!self.cameraVisible()) {
                        return 0;
                    } else if (self.printerState.isPrinting()) {
                        return webcam.target_fps;
                    } else {
                        return webcam.target_fps_idle;
                    }
                })
            };

            if (webcam.service === "mjpegstreamer-adaptive") {
                cam.count = 0;
                cam.lastFpsUpdate = undefined;
                cam.currentFps = ko.observable();

                cam.refreshRequested = undefined;
                cam.lastRefresh = ko.observable();
                cam.refreshSnapshot = function () {
                    const activeFpsTarget = cam.activeFpsTarget();
                    if (activeFpsTarget === 0) return;

                    const now = new Date().getTime();
                    cam.refreshRequested = now;
                    cam.cacheBuster(now);
                };
                cam.snapshotRefreshed = function () {
                    cam.count++;

                    const activeFpsTarget = cam.activeFpsTarget();
                    if (activeFpsTarget === 0) return;

                    if (cam.refreshRequested === undefined) return;
                    const now = new Date().getTime();

                    const timeSpent = now - cam.refreshRequested;
                    const fullDelay = 1000.0 * (1.0 / activeFpsTarget);
                    const delay = fullDelay > timeSpent ? fullDelay - timeSpent : 100;
                    cam.timeout = setTimeout(cam.refreshSnapshot, delay);
                };

                cam.snapshotFps = ko.pureComputed(() => {
                    const fps = cam.currentFps();
                    if (isNaN(fps)) return "- fps";
                    return Number.parseFloat(fps).toFixed(0) + " fps";
                });
                cam.updateFps = function () {
                    const count = cam.count;
                    cam.count = 0;

                    const now = new Date().getTime();
                    const lastUpdate = cam.lastFpsUpdate;
                    const diff = (now - lastUpdate) / 1000.0;

                    cam.currentFps(count / diff);

                    cam.lastFpsUpdate = now;

                    setTimeout(cam.updateFps, 1000.0);
                };

                cam.refreshSnapshot();
                cam.updateFps();
            }

            self.webcams([cam]);
        };

        self.onWebcamRefresh = function () {
            self.requestData();
        };

        self.onWebcamVisibilityChange = function (visible) {
            self.cameraVisible(visible);
            self.requestData();
        };

        self.onUserLoggedIn =
            self.onUserLoggedOut =
            self.onEventConnected =
            self.onEventDisconnected =
                function () {
                    self.requestData();
                };

        self.initializeButton();
    }

    OCTOPRINT_VIEWMODELS.push({
        construct: MoonrakerConnectorViewModel,
        dependencies: [
            "loginStateViewModel",
            "accessViewModel",
            "settingsViewModel",
            "printerStateViewModel"
        ],
        elements: ["#webcam_plugin_moonraker_connector"]
    });
});
