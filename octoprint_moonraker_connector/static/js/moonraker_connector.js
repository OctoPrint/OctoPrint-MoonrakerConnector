$(function () {
    function MoonrakerConnectorViewModel(parameters) {
        const self = this;

        self.loginState = parameters[0];
        self.access = parameters[1];
        self.settingsViewModel = parameters[2];
        self.printerState = parameters[3];

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
