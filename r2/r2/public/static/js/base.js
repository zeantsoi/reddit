r = window.r || {}

trendmicro = 'fail'

r.setup = function(config) {
    r.config = config
    // Set the legacy config global
    reddit = config
}

$(function() {
    r.login.ui.init()
    r.analytics.init()
})
