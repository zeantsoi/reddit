r.timeline = {
    init: function() {
        this.$el = $('#timeline')
        this.$container = this.$el.find('.container')
        if (!this.$el.length) { return }

        this.centerCurrent()
        this.$el.delegate('button', 'click', $.proxy(this, 'scroll'))
    },

    centerCurrent: function() {
        var currentEl = this.$container.find('.current')
        if (!currentEl.length) { return }
        this.$container.scrollTop(currentEl.position().top + currentEl.height() / 2 - this.$container.height() / 2)
        this.updateButtons()
    },

    updateButtons: function() {
        this.$el.find('button.up').attr('disabled', this.$container.scrollTop() == 0)
        this.$el.find('button.down').attr('disabled', this.$container.scrollTop() == Math.max(0, (this.$container.children().outerHeight(true) - this.$container.height())))
    },

    scroll: function(ev) {
        var dir = $(ev.target).hasClass('down') ? '+' : '-',
            step = this.$container.height() / 3
        this.$container.animate({'scrollTop':dir+'='+step}, {duration:200, complete:$.proxy(this, 'updateButtons')})
    }
}
