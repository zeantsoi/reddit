;(function(r, global, undefined) {
  var jail = document.getElementById('gtm-jail');
  var loaded = false;
  var queue = [];

  r.gtm = {

    _isReady: function(method, args) {
      if (!loaded) {
        queue.push({
          method: method,
          args: args,
        });

        return false;
      }

      return true;
    },

    trigger: function(eventName, payload) {
      if (!this._isReady('trigger', arguments)) {
        return;
      }

      if (payload) {
        this.set(payload);
      }

      r.frames.postMessage(jail.contentWindow, 'event.gtm', {
        event: eventName,
      });
    },

    set: function(data) {
      if (!this._isReady('set', arguments)) {
        return;
      }

      r.frames.postMessage(jail.contentWindow, 'data.gtm', data);
    },

  };

  r.frames.listen('gtm');

  r.frames.receiveMessageOnce('loaded.gtm', function() {
    loaded = true;

    queue.forEach(function(item) {
      var method = item.method;
      var args = item.args;

      r.gtm[method].apply(r.gtm, args);
    });
  });

  r.frames.receiveMessage('pixelError.gtm', function(e) {
    r.analytics.thirdPartyPixelFailureEvent(e.detail);
  });

  r.frames.receiveMessage('pixelSuccess.gtm', function(e) {
    r.analytics.thirdPartyPixelSuccessEvent(e.detail);
  });

})((this.r = this.r || {}), this);
