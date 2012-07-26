r.utils = {
    staticURL: function (item) {
        return r.config.static_root + '/' + item
    },

    currentOrigin: location.protocol+'//'+location.host,
}
