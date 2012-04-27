r = window.r || {}

r.setup = function(config) {
    r.config = config
    // Set the legacy config global
    reddit = config
}

$(function() {
    r.ui.init()
    r.login.ui.init()
    r.analytics.init()
})
