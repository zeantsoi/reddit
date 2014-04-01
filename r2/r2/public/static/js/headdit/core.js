r.headdit = {}

r.headdit.init = function() {
    this.box = new r.headdit.FrameView()
    this.box.render().$el.appendTo('body')
    r.headdit.commands.init()
}

r.headdit.FrameView = Backbone.View.extend({
    id: 'headdit-box',
    events: {
        'click .open-frame': 'openFrame',
        'click .close-frame': 'closeFrame'
    },

    initialize: function() {
        this.open = false
        this.teamBadge = null
    },

    render: function() {
        this.$el.empty()
        if (this.open) {
            $('<iframe>')
                .attr('src', '//' + r.config.media_domain + '/mediaembed/headdit')
                .appendTo(this.$el)
            this.$el.append('<button class="close-frame"></button>')
        } else {
            this.teamBadge = null
            this.$el.append('<button class="open-frame">headdit</button>')
        }
        return this
    },

    openFrame: function() {
        this.open = true
        this.render()
    },

    closeFrame: function() {
        this.open = false
        this.render()
    },

    setTeam: function(team) {
        if (this.teamBadge && this.teamBadge.team != team) {
            this.teamBadge.hide()
            this.teamBadge = null
        }

        if (!this.teamBadge) {
            this.teamBadge = new r.headdit.TeamBadge({team: team})
            this.teamBadge.render().$el.appendTo(this.$el)
            this.teamBadge.show()
        }
    }
})

r.headdit.commands = {
    cooldownTimeout: 200,
    holdTimeout: 1000
}

r.headdit.commands.init = function() {
    this.$links = $('.linklisting .link')
    this.curLinkIdx = 0
    this.selectLink(0)

    this._cooldownTimeout = null
    this._resetTimeout = null
    this.lastCmd = {}

    this.kittyMode = false

    window.addEventListener('message', _.bind(function(ev) {
        if (ev.origin != location.protocol + '//' + r.config.media_domain) {
            return
        }
        this.run(ev.data)
    }, this), false)
}

r.headdit.commands.selectLink = function(delta) {
    var idx = this.curLinkIdx + delta
    if (idx < 0 || idx > this.$links.length-1) {
        return
    }
    $(this.$links[this.curLinkIdx]).removeClass('head-focus')
    this.curLinkIdx = idx
    var $curLink = $(this.$links[idx])
    $curLink.addClass('head-focus')

    $('html, body').animate({
        scrollTop: $curLink.position().top - 500
    }, 350)
}

r.headdit.commands.cooldown = function() {
    this.lastCmd.overlay && this.lastCmd.overlay.hide()
}

r.headdit.commands.reset = function() {
    this.cooldown()
    this.lastCmd = {}
}

r.headdit.commands.touchTimeout = function() {
    this._cooldownTimeout && clearTimeout(this._cooldownTimeout)
    this._cooldownTimeout = setTimeout(_.bind(this.cooldown, this), this.cooldownTimeout)
    this._resetTimeout && clearTimeout(this._resetTimeout)
    this._resetTimeout = setTimeout(_.bind(this.reset, this), this.holdTimeout)
}

r.headdit.commands.run = function(cmd) {
    if (this.kittyMode) {
        return
    }

    if (cmd == 'orangered' || cmd == 'periwinkle') {
        r.headdit.box.setTeam(cmd)
        return
    }

    this.touchTimeout()

    var now = Date.now()

    if (this.lastCmd.cmd != cmd) {
        this.reset()
        this.lastCmd = {
            cmd: cmd,
            ts: now,
            overlay: null
        }
    }

    var $curLink = $(this.$links[this.curLinkIdx])

    if (cmd == 'upvote' || cmd == 'downvote' || cmd == 'open') {
        var cmdTime = now - this.lastCmd.ts
        if (cmdTime < this.holdTimeout) {
            if (!this.lastCmd.overlay && cmdTime >= .5) {
                this.lastCmd.overlay = new r.headdit.CommandOverlay({kind: cmd})
                this.lastCmd.overlay.render().$el.appendTo('body')
            }
            this.lastCmd.overlay && this.lastCmd.overlay.show()
            return
        }

        if (cmd == 'upvote') {
            $curLink
                .removeClass('downvoted')
                .addClass('upvoted')
                .find('.arrow.up')
                .click()
        } else if (cmd == 'downvote') {
            $curLink
                .removeClass('upvoted')
                .addClass('downvoted')
                .find('.arrow.down')
                .click()
        } else if (cmd == 'open') {
            window.open($curLink.find('a.title').attr('href'), '_blank')
        }

        // cooldown
        this.lastCmd.ts = now + this.holdTimeout
        this.lastCmd.overlay.onRan()
        this.lastCmd.overlay.hide()
        this.lastCmd.overlay = null
    }

    if (cmd == 'next') {
        this.selectLink(1)
    } else if (cmd == 'prev') {
        this.selectLink(-1)
    }

    var kittyURL = '/user/lieutenantmeowmeow/m/meow'
    if (cmd == 'kitty' && !this.kittyMode && location.pathname != kittyURL) {
        this.kittyMode = true
        this.kittyAlert = new r.headdit.KittyAlert()
        this.kittyAlert.render().$el.appendTo('body')
        this.kittyAlert.startBlinking()
        setTimeout(function() {
            window.location = kittyURL
        }, 2000)
    }
}

r.headdit.CommandOverlay = Backbone.View.extend({
    className: 'command-overlay',

    initialize: function(options) {
        this.kind = options.kind
    },

    render: function() {
        this.$el
            .empty()
            .addClass(this.kind)
            .append('<img class="action" src="' + r.utils.staticURL('headdit/' + this.kind + '.svg') + '">')
        return this
    },

    show: function() {
        this._hideTimeout && clearTimeout(this._hideTimeout)
        this._hideTimeout = null
        setTimeout(_.bind(function() {
            this.$el.addClass('showing')
        }, this), 0)
    },

    onRan: function() {
        this.$el.addClass('ran')
    },

    hide: function() {
        this.$el.removeClass('showing')
        this._hideTimeout = setTimeout(_.bind(function() {
            this.remove()
        }, this), 500)
    }
})

r.headdit.KittyAlert = Backbone.View.extend({
    className: 'kitty-alert',

    render: function() {
        this.$el.html('KITTY DETECTED')
        return this
    },

    startBlinking: function() {
        this.interval = setInterval(_.bind(this.blink, this), 300)
    },

    blink: function() {
        this.$el.toggleClass('blink')
    }
})

r.headdit.TeamBadge = Backbone.View.extend({
    className: 'team-badge',

    initialize: function(options) {
        this.team = options.team
    },

    render: function() {
        this.$el.addClass('team-' + this.team)
        if (this.team == 'orangered') {
            this.$el.html('team orangered')
        } else if (this.team == 'periwinkle') {
            this.$el.html('team periwinkle')
        }
        return this
    },

    show: function() {
        setTimeout(_.bind(function() {
            this.$el.addClass('showing')
        }, this), 0)
    },

    hide: function() {
        this.$el.removeClass('showing')
        setTimeout(_.bind(function() {
            this.remove()
        }, this), 500)
    }
})

$(function() {
    r.headdit.init()
})
