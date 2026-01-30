$(function () {
    function MoonrakerConnectorViewModel(parameters) {
        const self = this;

        self.loginState = parameters[0];
        self.access = parameters[1];
        self.settingsViewModel = parameters[2];
        self.printerState = parameters[3];

        self.isMoonrakerReady = ko.pureComputed(function() {
            // I'd like to check for moonraker connection
            // and see if klipper is connected, as some commands
            // can be sent even if !isOperational() and that's be
            // a better check, that or restart klipper maybe belongs
            // in the Connection pane?
            return self.printerState.isOperational();
        });

        self.btnReloadConfigClick = function() {
            //OctoPrint.control.sendGcode('RESTART');
            showConfirmationDialog({
                message: gettext("<strong>This will restart the Klipper host.</strong></p><p>This might disrupt any ongoing operations related to Klipper."),
                onproceed: function() {
                    OctoPrint.simpleApiCommand(
                        "moonraker_connector",
                        "restart_host"
                    ).done(function(response) {
                        if (response.success) {
                            new PNotify({
                                title: gettext("Success"),
                                text: gettext("Klipper host restart command sent"),
                                type: "success"
                            });
                        } else {
                            new PNotify({
                                title: gettext("Failed"),
                                text: gettext("Failed to send Klipper host restart command: ") + response.message,
                                type: "error"
                            });
                        }
                    }).fail(function(jqXHR, textStatus, errorThrown) {
                        new PNotify({
                            title: gettext("Error"),
                            text: gettext("Failed to execute command: ") + jqXHR.responseJSON.message,
                            type: "error"
                        });
                    });
                }
            });
        }

        self.btnFirmwareRestartClick = function() {
            //OctoPrint.control.sendGcode('FIRMWARE_RESTART');
            showConfirmationDialog({
                message: gettext("<strong>This will restart the Klipper firmware.</strong></p><p>This might disrupt any ongoing operations related to Klipper."),
                onproceed: function() {
                    OctoPrint.simpleApiCommand(
                        "moonraker_connector",
                        "restart_firmware"
                    ).done(function(response) {
                        if (response.success) {
                            new PNotify({
                                title: gettext("Success"),
                                text: gettext("Klipper firmware restart command sent"),
                                type: "success"
                            });
                        } else {
                            new PNotify({
                                title: gettext("Failed"),
                                text: gettext("Failed to send Klipper firmware restart command: ") + response.message,
                                type: "error"
                            });
                        }
                    }).fail(function(jqXHR, textStatus, errorThrown) {
                        new PNotify({
                            title: gettext("Error"),
                            text: gettext("Failed to execute command: ") + jqXHR.responseJSON.message,
                            type: "error"
                        });
                    });
                }
            });
        }

        self.btnKlipperRestartClick = function() {
            showConfirmationDialog({
                message: "<strong>" + gettext("This will restart the Klipper service.") + "</strong></p><p>" + gettext("This might disrupt any ongoing operations related to Klipper."),
                onproceed: function() {
                    OctoPrint.simpleApiCommand(
                        "moonraker_connector",
                        "restart_klipper_service"
                    ).done(function(response) {
                        if (response.success) {
                            new PNotify({
                                title: gettext("Success"),
                                text: gettext("Klipper service restart command sent"),
                                type: "success"
                            });
                        } else {
                            new PNotify({
                                title: gettext("Failed"),
                                text: gettext("Failed to send Klipper service restart command: ") + response.message,
                                type: "error"
                            });
                        }
                    }).fail(function(jqXHR, textStatus, errorThrown) {
                        new PNotify({
                            title: gettext("Error"),
                            text: gettext("Failed to execute command: ") + jqXHR.responseJSON.message,
                            type: "error"
                        });
                    });
                }
            });
        }

        self.initializeButton = function() {
            var buttonContainer = $('#job_print')[0].parentElement;

            var parentContainer = document.createElement("div");
            parentContainer.id = "moonraker_connector_wrapper";

            var container = document.createElement("div");
            container.classList.add("row-fluid", "print-control");
            container.style.marginTop = "10px";
            // container.setAttribute("data-bind", "visible: isOperational() && loginState.isUser()");

            var btnReloadConfig = document.createElement("button");
            btnReloadConfig.id = "job_reload_config";
            btnReloadConfig.title = gettext("Reload configuration file and performs an internal reset of the host software. It does not clear the error state from the micro-controller.");
            btnReloadConfig.classList.add("btn");
            btnReloadConfig.classList.add("span6");
            // btnReloadConfig.setAttribute("data-bind", "enable: isOperational() && loginState.isUser()");
            btnReloadConfig.addEventListener("click", self.btnReloadConfigClick);

            var btnReloadConfigIcon = document.createElement("i");
            btnReloadConfigIcon.classList.add("fas", "fa-sync-alt");
            btnReloadConfigIcon.style.marginRight = "5px";
            btnReloadConfig.appendChild(btnReloadConfigIcon);

            var btnReloadConfigText = document.createElement("span");
            btnReloadConfigText.textContent = gettext("Reload Config");
            btnReloadConfig.appendChild(btnReloadConfigText);

            container.appendChild(btnReloadConfig);

            var btnFirmwareRestart = document.createElement("button");
            btnFirmwareRestart.id = "job_firmware_restart";
            btnFirmwareRestart.title = gettext("Reload configuration file and performs an internal reset of the host software, but it also clears any error states from the micro-controller.");
            btnFirmwareRestart.classList.add("btn");
            btnFirmwareRestart.classList.add("span6");
            // btnFirmwareRestart.setAttribute("data-bind", "enable: isOperational() && loginState.isUser()");
            btnFirmwareRestart.addEventListener("click", self.btnFirmwareRestartClick);

            var btnFirmwareRestartIcon = document.createElement("i");
            btnFirmwareRestartIcon.classList.add("fas", "fa-microchip");
            btnFirmwareRestartIcon.style.marginRight = "5px";
            btnFirmwareRestart.appendChild(btnFirmwareRestartIcon);

            var btnFirmwareRestartText = document.createElement("span");
            btnFirmwareRestartText.textContent = gettext("Firmware Restart");
            btnFirmwareRestart.appendChild(btnFirmwareRestartText);
            
            container.appendChild(btnFirmwareRestart);

            parentContainer.append(container);

            var container2 = document.createElement("div");
            container2.classList.add("row-fluid", "print-control");
            container2.style.marginTop = "10px";
            // container2.setAttribute("data-bind", "visible: isOperational() && loginState.isUser()");

            var btnKlipperRestart = document.createElement("button");
            btnKlipperRestart.id = "job_klipper_restart";
            btnKlipperRestart.title = gettext("Restart klipper process.");
            btnKlipperRestart.classList.add("btn");
            btnKlipperRestart.classList.add("span12");
            // btnKlipperRestart.setAttribute("data-bind", "enable: isOperational() && loginState.isUser()");
            btnKlipperRestart.addEventListener("click", self.btnKlipperRestartClick);

            var btnKlipperRestartIcon = document.createElement("i");
            btnKlipperRestartIcon.classList.add("fas", "fa-power-off");
            btnKlipperRestartIcon.style.marginRight = "5px";
            btnKlipperRestart.appendChild(btnKlipperRestartIcon);

            var btnKlipperRestartText = document.createElement("span");
            btnKlipperRestartText.textContent = gettext("Restart Klipper Service");
            btnKlipperRestart.appendChild(btnKlipperRestartText);

            container2.appendChild(btnKlipperRestart);

            parentContainer.append(container2);

            buttonContainer.after(parentContainer);
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
        elements: [
            "#moonraker_connector_wrapper",
            "#webcam_plugin_moonraker_connector"
        ]
    });
});
