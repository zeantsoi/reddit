r.insanity = {
    _backoffTime: 1000,

    init: function () {
        var websocketsAvailable = 'WebSocket' in window
        var onFrontPage = $('body').is('.front-page')

        if (websocketsAvailable && onFrontPage && r.config.insanity) {
            this.$headerImage = $('#header-img-a img')

            if (this.$headerImage.length == 0) {
                r.warn('WS: a sprited header image is too sane. bailing out.')
                return
            }

            this._originalHeaderUrl = this.$headerImage.attr('src')
            this._failedConnectionAttempts = 0
            this._totalConnectionAttempts = 0
            this._connect()
        }
    },

    _connect: function () {
        r.debug('WS: attempting to connect')

        if (this._failedConnectionAttempts > 3) {
            r.warn('WS: could not establish connection. giving up. :(')
            return
        }

        if (this._totalConnectionAttempts > 6) {
            r.warn('WS: i have tried connecting too many times. goodbye.')
            return
        }

        this.socket = new WebSocket(r.config.insanity)
        this.socket.onopen = $.proxy(this, '_onSocketOpen')
        this.socket.onmessage = $.proxy(this, '_onMessage')
        this.socket.onclose = $.proxy(this, '_onSocketClose')
        this._totalConnectionAttempts += 1
    },

    _onSocketOpen: function () {
        r.debug('WS: connected')
        this._failedConnectionAttempts = 0
    },

    _onMessage: function (ev) {
        r.debug('WS: got new logo url ' + ev.data)
        this._setHeaderImage(ev.data)
    },

    _onSocketClose: function (ev) {
        this._setHeaderImage(this._originalHeaderUrl)

        var delay = this._backoffTime * Math.pow(2, this._failedConnectionAttempts)
        r.log('WS: lost connection/failed to connect; will try again in ' + delay + ' ms')
        setTimeout($.proxy(this, '_connect'), delay)
        this._failedConnectionAttempts += 1
    },

    _setHeaderImage: function (url) {
        this.$headerImage.attr('src', url)
    }
}
