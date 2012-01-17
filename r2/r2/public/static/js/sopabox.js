r.ui.SOPABox = function(el) {
    r.ui.Base.apply(this, arguments)
    this.$el.find('.hide').click($.proxy(this, 'hide'))
    this.interval = setInterval($.proxy(this, 'update'), 1000)
    if (this.update() && !$.cookie('hidesopabox')) {
        this.$el.show()
    }
}
r.ui.SOPABox.prototype = {
    update: function() {
        function pad(n) {
            // via MDN: https://developer.mozilla.org/en/JavaScript/Reference/Global_Objects/Date#Example:_ISO_8601_formatted_dates
            return n < 10 ? '0'+n : n
        }
        var remaining = (Date.UTC(2012, 0, 18, 13) - new Date)/1000

        if (remaining > 0) {
            var hours = Math.floor(remaining / (60*60))
                minutes = Math.floor(remaining % (60*60) / 60)
                seconds = Math.floor(remaining % 60)
            this.$el.find('.duration').text(pad(hours)+'h '+pad(minutes)+'m '+pad(seconds)+'s')
            return true
        } else {
            this.$el.addClass("live")
            clearInterval(this.interval)
            return false
        }
    },

    hide: function() {
        $.cookie('hidesopabox', '1', {domain:r.config.cur_domain, path:'/', expires:7})
        this.$el.hide()
    }
}

r.sopabox = {
    init: function() {
        var sopabox = $('#sopabox')
        if (sopabox.length) {
            r.ui.sopabox = new r.ui.SOPABox(sopabox)
        }
    }
}
