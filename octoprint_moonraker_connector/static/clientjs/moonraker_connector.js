(function (global, factory) {
    if (typeof define === "function" && define.amd) {
        define(["OctoPrintClient"], factory);
    } else {
        factory(global.OctoPrintClient);
    }
})(this, function (OctoPrintClient) {
    var OctoPrintMoonrakerConnectorClient = function (base) {
        this.base = base;
    };

    OctoPrintMoonrakerConnectorClient.prototype.get = function (opts) {
        return this.base.simpleApiGet("moonraker_connector", opts);
    };

    OctoPrintClient.registerPluginComponent(
        "moonraker_connector",
        OctoPrintMoonrakerConnectorClient
    );
    return OctoPrintMoonrakerConnectorClient;
});
