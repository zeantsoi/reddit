r.WebSocket = function (url) {
    this._url = url
    this._connectionAttempts = 0

    this.on({
        'message:refresh': this._onRefresh,
    }, this)
}
_.extend(r.WebSocket.prototype, Backbone.Events, {
    _backoffTime: 2000,
    _maximumRetries: 9,
    _retryJitterAmount: 3000,

    start: function () {
        var websocketsAvailable = 'WebSocket' in window
        if (websocketsAvailable) {
            this._connect()
        }
    },

    _connect: function () {
        r.debug('websocket: connecting')
        this.trigger('connecting')

        this._connectionStart = Date.now()
        this._socket = new WebSocket(this._url)
        this._socket.onopen = _.bind(this._onOpen, this)
        this._socket.onmessage = _.bind(this._onMessage, this)
        this._socket.onclose = _.bind(this._onClose, this)

        this._connectionAttempts += 1
    },

    _sendStats: function (payload) {
      if (!r.config.stats_domain) {
        return
      }

      $.ajax({
        type: 'POST',
        url: r.config.stats_domain,
        data: JSON.stringify(payload),
        contentType: 'application/json; charset=utf-8',
      })
    },

    _onOpen: function (ev) {
        r.debug('websocket: connected')
        this.trigger('connected')
        this._connectionAttempts = 0

        this._sendStats({
          websocketPerformance: {
            connectionTiming: Date.now() - this._connectionStart,
          },
        })
    },

    _onMessage: function (ev) {
        var parsed = JSON.parse(ev.data)
        r.debug('websocket: received "' + parsed.type + '" message')
        this.trigger('message message:' + parsed.type, parsed.payload)
    },

    _onRefresh: function () {
        // delay a random amount to reduce thundering herd
        var delay = Math.random() * 300 * 1000
        setTimeout(function () { location.reload() }, delay)
    },

    _onClose: function (ev) {
        if (this._connectionAttempts < this._maximumRetries) {
            var baseDelay = this._backoffTime * Math.pow(2, this._connectionAttempts),
                jitter = (Math.random() * this._retryJitterAmount) - (this._retryJitterAmount / 2),
                delay = Math.round(baseDelay + jitter)
            r.debug('websocket: connection lost (' + ev.code + '), reconnecting in ' + delay + 'ms')
            r.debug("(can't connect? Make sure you've allowed https access in your browser.)")
            this.trigger('reconnecting', delay)
            setTimeout(_.bind(this._connect, this), delay)
        } else {
            r.debug('websocket: maximum retries exceeded. bailing out')
            this.trigger('disconnected')
        }

        this._sendStats({
          websocketError: {
            error: 1,
          },
        })
    },

    _verifyLocalStorage: function(keyname) {
        // Check if local storage is supported
        var PERSIST_SYNCED_KEYS_KEY = '__synced_local_storage_%(keyname)s__'.format({keyname: keyname});
        try {
            store.safeSet(
                PERSIST_SYNCED_KEYS_KEY,
                store.safeGet(PERSIST_SYNCED_KEYS_KEY) || ''
            )
        } catch (err) {
            return false;
        }
        return true;
    },

    startPerBrowser: function(keyname, websocketUrl, websocketEvents, websocketStorageEvents) {
        if (!this._verifyLocalStorage(keyname)) {
            return false;
        }
        var now = new Date();
        var date = store.safeGet(keyname) || '';

        // If a websocket hasn't written to storage in 15 seconds,
        // open a new one
        if (!date || now - new Date(date) > 15000) {
            this.on(websocketEvents);
            this.start();
            store.safeSet(keyname + '-websocketUrl', websocketUrl);
        }
        this._keepTrackOfHeartbeat(keyname, websocketEvents, websocketUrl);

        // Listen for storage events to see if a websocket message
        // has been broadcast
        window.addEventListener('storage', websocketStorageEvents);
    },

    _writeHeartbeat: function(keyname, websocketEvents, websocketUrl) {
        store.safeSet(keyname, new Date());
        var websocketInterval = setInterval(function() {
            var now = new Date();
            var storedDate = store.safeGet(keyname);
            if (store.safeGet(keyname + '-websocketUrl') !== websocketUrl) {
                // Another websocket is currently open so close this one
                if (!!storedDate && now - new Date(storedDate) < 5000) {
                    this._maximumRetries = 0;
                    this._socket.close();
                    clearInterval(websocketInterval);
                    this._watchHeartbeat(keyname, websocketEvents, websocketUrl);
                }
            }
        store.safeSet(keyname, new Date());
        }.bind(this), 5000);
    },

    _watchHeartbeat: function(keyname, websocketEvents, websocketUrl) {
        var noWebsocketInterval = setInterval(function() {
            var now = new Date();
            var date = store.safeGet(keyname) || '';

            // The websocket heartbeat hasn't been updated recently, so
            // open a new websocket, clear this heartbeat checker, and
            // start updating the heartbeat instead.
            if (!date || now - new Date(date) > 15000) {
                this.on(websocketEvents);
                this.start();
                store.safeSet(keyname + '-websocketUrl', websocketUrl);
                clearInterval(noWebsocketInterval);
                this._writeHeartbeat(keyname, websocketEvents, websocketUrl);
            }
        }.bind(this), 15000);
    },

    _keepTrackOfHeartbeat: function(keyname, websocketEvents, websocketUrl) {
        if (store.safeGet(keyname + '-websocketUrl') === websocketUrl) {
            // This is now the tab with the websocket, keep a timestamp
            // rewriting every 5 seconds in local storage
            this._writeHeartbeat(keyname, websocketEvents, websocketUrl);
        } else {
            // Otherwise, poll every 15 seconds to see if the timestamp is
            // old, which means we'd need to open a websocket
            this._watchHeartbeat(keyname, websocketEvents, websocketUrl);
        }
    },
})
