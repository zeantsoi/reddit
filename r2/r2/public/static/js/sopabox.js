r.ui.SOPABox = function(el) {
    r.ui.Base.apply(this, arguments)
    this.$el.find('.hide').click($.proxy(this, 'hide'))
    setInterval($.proxy(this, 'update'), 1000)
    this.update()
    if (!$.cookie('hidesopabox')) {
        this.$el.show()
    }
}
r.ui.SOPABox.prototype = {
    update: function() {
        function pad(n) {
            // via MDN: https://developer.mozilla.org/en/JavaScript/Reference/Global_Objects/Date#Example:_ISO_8601_formatted_dates
            return n < 10 ? '0'+n : n
        }
        var remaining = (new Date(2011, 11, 15, 10) - new Date)/1000

        if (remaining > 0) {
            var hours = Math.floor(remaining / (60*60))
                minutes = Math.floor(remaining % (60*60) / 60)
                seconds = Math.floor(remaining % 60)
            this.$el.find('.duration').text(pad(hours)+'h '+pad(minutes)+'m '+pad(seconds)+'s')
            this.$el.find('.countdown').show()
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
