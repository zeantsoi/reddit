!function(r) {
  'use strict';

  function _postData(eventInfo) {
    $.ajax({
      method: 'POST',
      url: eventInfo.url + '?' + jQuery.param(eventInfo.query),
      data: eventInfo.data,
      contentType: 'text/plain',
      complete: eventInfo.done,
    });
  }

  function _calculateHash(key, data) {
    var hash = CryptoJS.HmacSHA256(data, key);
    return hash.toString(CryptoJS.enc.Hex);
  }

  function _testAdblock() {
    var $el = $('#adblock-test');

    return (!$el.length || $el.is(':hidden'));
  }

  function _flush() {
    var done = _queue.map(function(calledWith) {
      // `calledWith.track` is an array of arguments for:
      //    function(eventTopic, eventName, eventPayload, options) { ...
      // `calledWith.done` is the callback from:
      //    overrides.send = function(done) { ...
      r.events.track.apply(r.events.track, calledWith.track);

      return calledWith.done;
    }.bind(r.analytics));

    // call all the callbacks after the payloads are sent.
    r.events.send(function() {
      _.invoke(done, 'call');
    });

    // clear the queue.
    _queue = [];
  }

  var _tracker;
  var _queue = [];

  r.events = {
    init: function() {
      var config = r.config;

      if (config.events_collector_key &&
          config.events_collector_secret &&
          config.events_collector_url) {
        _tracker = new EventTracker(
          config.events_collector_key,
          config.events_collector_secret,
          _postData,
          config.events_collector_url,
          'reddit.com',
          _calculateHash
        );

        // `truthy` means skip, undefined topics will therefore be using a 100%
        // sample
        this.sampling = {
          'ad_serving_events': Math.random() > config.ad_serving_events_sample_rate,
        };
      }

      this.contextData = this._getContextData(config);
      this.initialized = true;

      // flush any events that were queued before the module
      // completed initializing.
      _flush();
    },

    _getContextData: function(config) {
      var contextData = {
        dnt: window.DO_NOT_TRACK,
        language: document.getElementsByTagName('html')[0].getAttribute('lang'),
        link_id: config.cur_link ? r.utils.fullnameToId(config.cur_link) : null,
        loid: null,
        loid_created: null,
        referrer_url: document.referrer || '',
        referrer_domain: null,
        sr_id: config.cur_site ? r.utils.fullnameToId(config.cur_site) : null,
        sr_name: config.post_site || null,
        user_id: null,
        user_name: null,
        user_in_beta: config.pref_beta,
      };

      if (config.feature_adblock_test) {
        contextData.adblock = _testAdblock();
      }

      if (config.user_id) {
        contextData.user_id = config.user_id;
        contextData.user_name = config.logged;
      } else {
        var tracker = new redditlib.Tracker();
        var loggedOutData = tracker.getTrackingData();
        if (loggedOutData && loggedOutData.loid) {
          contextData.loid = loggedOutData.loid;
          if (loggedOutData.loidcreated) {
            contextData.loid_created = decodeURIComponent(loggedOutData.loidcreated);
          }
        }
      }

      if (document.referrer) {
        var referrerDomain = document.referrer.match(/\/\/([^\/]+)/);
        if (referrerDomain && referrerDomain.length > 1) {
          contextData.referrer_domain = referrerDomain[1];
        }
      }

      if ($('body').hasClass('comments-page')) {
        contextData.page_type = 'comments';
      } else if ($('body').hasClass('listing-page')) {
        contextData.page_type = 'listing';

        if (config.cur_listing) {
          contextData.listing_name = config.cur_listing;
        }
      }

      if (config.expando_preference) {
        contextData.expando_preference = config.expando_preference;
      }

      if (config.pref_no_profanity) {
        contextData.media_preference_hide_nsfw = config.pref_no_profanity
      }

      return contextData;
    },

    _addContextData: function(properties, payload) {
      /* jshint sub: true */
      properties = properties || [];
      payload = payload || {};

      if (this.contextData.user_id) {
        payload['user_id'] = this.contextData.user_id;
        payload['user_name'] = this.contextData.user_name;
      } else {
        payload['loid'] = this.contextData.loid;
        payload['loid_created'] = decodeURIComponent(this.contextData.loid_created);
      }

      properties.forEach(function(contextProperty) {
        /* jshint eqnull: true */
        if (this.contextData[contextProperty] != null) {
          payload[contextProperty] = this.contextData[contextProperty];
        }
      }.bind(this));

      return payload;
    },

    track: function(eventTopic, eventName, eventPayload, options) {
      options = options || {};

      var overrides = {};

      if (!this.initialized) {
        var calledWith = {};

        calledWith.track = _.toArray(arguments);

        _queue.push(calledWith);

        // assign the callback by ref to `calledWith`
        // so we can call it when the queue is flushed.
        overrides.send = function(done) {
          calledWith.done = done;
          return this;
        }.bind(this);
      } else {
        var payload = this._addContextData(options.contextProperties, eventPayload);

        if (_tracker && !this.sampling[eventTopic]) {
          _tracker.track(eventTopic, eventName, payload);
        }
      }

      return $.extend({}, this, overrides);
    },

    send: function(done) {
      if (_tracker) {
        _tracker.send(done);
      } else if (typeof done === 'function') {
        done();
      }
      return this;
    }
  };

}(r);
