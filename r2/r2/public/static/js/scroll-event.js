!function(r) {
  var EVENT_TOPIC = "scroll_events";
  var EVENT_TYPE = "scroll";
  var EVENT_DELAY = 60 * 1000;
  var UPDATE_INTERVAL = 5 * 1000;
  var SCROLL_UPDATE_THROTTLE = 500;
  var SESSION_KEY = ['reddit.event', EVENT_TOPIC, EVENT_TYPE].join('/');

  r.scrollEvent = {
    init: function() {
      if (!r.screenviewEvent) { return; }

      var previousEvent = this._getStoredEventData();
      if (previousEvent) {
        // queue the event instead of sending so it will get batched with the 
        // screenview event
        r.analytics.queueEvent(EVENT_TOPIC, EVENT_TYPE, undefined, previousEvent);
      }

      var defaultFields = r.screenviewEvent.getDefaultEventFields();
      var customFields = r.screenviewEvent.getCustomEventFields();
      var eventPayload = r.events.addContextData(defaultFields, customFields);
      
      eventPayload.content_seen_percentage = 0;
      eventPayload.scroll_percentage = 0;

      var $body = $('body');
      var $window = $(window);
      var maxScrollTop = 0;

      var _updateScrollData = _.throttle(function () {
        var scrolled = $body.scrollTop();
        var windowHeight = $window.height();
        var pageHeight = $body.height();
        var scrollableHeight = pageHeight - windowHeight;
        var contentSeen = (scrolled + windowHeight) / pageHeight;
        var scrolledPercent = 0;
        if (scrollableHeight > 0) {
          scrolledPercent = scrolled / (pageHeight - windowHeight);
        }

        eventPayload.content_seen_percentage = Math.min(
            1, Math.max(eventPayload.content_seen_percentage, contentSeen)
        );
        eventPayload.scroll_percentage = Math.min(
            1, Math.max(eventPayload.scroll_percentage, scrolledPercent)
        );
      }, SCROLL_UPDATE_THROTTLE);

      $(window).on('scroll', _updateScrollData);

      var intervalID = setInterval(function() {
        this._setStoredEventData(eventPayload);
      }.bind(this), UPDATE_INTERVAL);

      _updateScrollData();
      this._setStoredEventData(eventPayload);

      setTimeout(function() {
        clearInterval(intervalID);
        $(window).off('scroll', _updateScrollData);
        // since we're using storage, it's possible that the event was picked up
        // and fired from another tab, so make sure it still exists.
        if (this._getStoredEventData()) {
          r.analytics.sendEvent(EVENT_TOPIC, EVENT_TYPE, undefined, eventPayload);
          this._clearStoredEventData();
        }
      }.bind(this), EVENT_DELAY);
    },

    _getStoredEventData: function() {
      try {
        return JSON.parse(sessionStorage.getItem(SESSION_KEY));
      } catch (e) {
        return null;
      }
    },

    _setStoredEventData: function(eventData) {
      try {
        sessionStorage.setItem(SESSION_KEY, JSON.stringify(eventData));
        return true;
      } catch (e) {
        return false;
      }
    },

    _clearStoredEventData: function() {
      try {
        sessionStorage.removeItem(SESSION_KEY);
      } catch (e) {
      }
    },
  };
}(r);
