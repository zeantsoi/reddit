r.analytics = {
  init: function() {
    // these guys are relying on the custom 'onshow' from jquery.reddit.js
    $(document).delegate(
      '.organic-listing .promotedlink.promoted',
      'onshow',
      _.bind(function(ev) {
        this.fireTrackingPixel(ev.target);
      }, this)
    );

    $('.promotedlink.promoted:visible').trigger('onshow');

    // dont track sponsor's activity
    r.analytics.addEventPredicate('ads', function() {
      return !r.config.is_sponsor;
    });

    // virtual page tracking for ads funnel
    if (r.config.ads_virtual_page) {
      r.analytics.fireFunnelEvent('ads', r.config.ads_virtual_page);
    }

    var url = r.config.tracker_url;
    var params = {
      dnt: window.DO_NOT_TRACK,
    };

    if (!r.config.user_id) {
      var tracker = new redditlib.Tracker();
      var loggedOutData = tracker.getTrackingData();
      if (loggedOutData && loggedOutData.loid) {
        params.loid = loggedOutData.loid;
        if (loggedOutData.loidcreated) {
          params['loidcreated'] = loggedOutData.loidcreated
        }
      }
    }

    r.analytics.firePageTrackingPixel(url, params, r.analytics.stripAnalyticsParams);
  },

  _eventPredicates: {},

  addEventPredicate: function(category, predicate) {
    var predicates = this._eventPredicates[category] || [];

    predicates.push(predicate);

    this._eventPredicates[category] = predicates;
  },

  shouldFireEvent: function(category/*, arguments*/) {
    var args = _.rest(arguments);

    return !this._eventPredicates[category] ||
        this._eventPredicates[category].every(function(fn) {
          return fn.apply(this, args);
        });
  },

  _isGALoaded: false,

  isGALoaded: function() {
    // We've already passed this test, just return `true`
    if (this._isGALoaded) {
      return true;
    }

    // GA hasn't tried to load yet, so we can't know if it
    // will succeed.
    if (_.isArray(_gaq)) {
      return undefined;
    }

    var test = false;

    _gaq.push(function() {
      test = true;
    });

    // Remember the result, so we only have to run this test once
    // if it passes.
    this._isGALoaded = test;

    return test;
  },

  _wrapCallback: function(callback) {
    var original = callback;

    original.called = false;
    callback = function() {
      if (!original.called) {
        original();
        original.called = true;
      }
    };

    // GA may timeout.  ensure the callback is called.
    setTimeout(callback, 500);

    return callback;
  },

  fireFunnelEvent: function(category, action, options, callback) {
    options = options || {};
    callback = callback || window.Function.prototype;

    var page = '/' + _.compact([category, action, options.label]).join('-');

    // if it's for Gold tracking and we have new _ga available
    // then use it to track the event; otherwise, fallback to old version
    if (options.tracker &&
        '_ga' in window &&
        window._ga.getByName &&
        window._ga.getByName(options.tracker)) {
      window._ga(options.tracker + '.send', 'pageview', {
        'page': page,
        'hitCallback': callback
      });

      if (options.value) {
        window._ga(options.tracker + '.send', 'event', category, action, options.label, options.value);
      }

      return;
    }

    if (!window._gaq || !this.shouldFireEvent.apply(this, arguments)) {
      callback();
      return;
    }

    var isGALoaded = this.isGALoaded();

    if (!isGALoaded) {
      callback = this._wrapCallback(callback);
    }

    // Virtual page views are needed for a funnel to work with GA.
    // see: http://gatipoftheday.com/you-can-use-events-for-goals-but-not-for-funnels/
    _gaq.push(['_trackPageview', page]);

    // The goal can have a conversion value in GA.
    if (options.value) {
      _gaq.push(['_trackEvent', category, action, options.label, options.value]);
    }

    _gaq.push(callback);
  },

  fireGAEvent: function(category, action, opt_label, opt_value, opt_noninteraction, callback) {
    opt_label = opt_label || '';
    opt_value = opt_value || 0;
    opt_noninteraction = !!opt_noninteraction;
    callback = callback || function() {};

    if (!window._gaq || !this.shouldFireEvent.apply(this, arguments)) {
      callback();
      return;
    }

    var isGALoaded = this.isGALoaded();

    if (!isGALoaded) {
      callback = this._wrapCallback(callback);
    }

    _gaq.push(['_trackEvent', category, action, opt_label, opt_value, opt_noninteraction]);
    _gaq.push(callback);
  },

  fireTrackingPixel: function(el) {
    var $el = $(el);
    var onCommentsPage = $('body').hasClass('comments-page');

    if ($el.data('trackerFired') || onCommentsPage) {
      return;
    }

    var adBlockIsEnabled = $('#siteTable_organic').is(":hidden");
    var pixel = new Image();
    var impPixel = $el.data('impPixel');

    if (impPixel && !adBlockIsEnabled) {
      pixel.src = impPixel;
    }

    if (!adBlockIsEnabled) {
      var thirdPartyTrackingUrl = $el.data('thirdPartyTrackingUrl');
      if (thirdPartyTrackingUrl) {
        var thirdPartyTrackingImage = new Image();
        thirdPartyTrackingImage.src = thirdPartyTrackingUrl;
      }

      var thirdPartyTrackingUrl2 = $el.data('thirdPartyTrackingTwoUrl');
      if (thirdPartyTrackingUrl2) {
        var thirdPartyTrackingImage2 = new Image();
        thirdPartyTrackingImage2.src = thirdPartyTrackingUrl2;
      }
    }

    var adServerPixel = new Image();
    var adServerImpPixel = $el.data('adserverImpPixel');
    var adServerClickUrl = $el.data('adserverClickUrl');

    if (adServerImpPixel && !adBlockIsEnabled) {
      adServerPixel.src = adServerImpPixel;
    }

    $el.data('trackerFired', true);
  },

  fireUITrackingPixel: function(action, srname, extraParams) {
    var pixel = new Image();
    pixel.src = r.config.uitracker_url + '?' + $.param(
      _.extend(
        {
          act: action,
          sr: srname,
          r: Math.round(Math.random() * 2147483647), // cachebuster
        },
        r.analytics.breadcrumbs.toParams(),
        extraParams
      )
    );
  },

  firePageTrackingPixel: function(url, params, callback) {
    if (!url) { return; }

    params = params || {};

    var querystring = [
      'r=' + Math.random(),
    ];

    var referrer = document.referrer || '';
    var referrerDomain = referrer.match(/\/\/([^\/]+)/);

    if (referrerDomain && referrerDomain.length > 1) {
      querystring.push('referrer_domain=' + encodeURIComponent(referrerDomain[1]));
    }

    for(var p in params) {
      if (params.hasOwnProperty(p)) {
        querystring.push(
          encodeURIComponent(p) + '=' + encodeURIComponent(params[p])
        );
      }
    }

    var pixel = new Image();
    pixel.onload = pixel.onerror = callback;
    pixel.src = url + '&' + querystring.join('&');
  },

  // If we passed along referring tags to this page, after it's loaded, remove them from the URL so that 
  // the user can have a clean, copy-pastable URL. This will also help avoid erroneous analytics if they paste the URL
  // in an email or something.
  stripAnalyticsParams: function() {
    var hasReplaceState = !!(window.history && window.history.replaceState);
    var params = $.url().param();
    var stripParams = ['ref', 'ref_source', 'ref_campaign'];
    var strippedParams = _.omit(params, stripParams);

    if (hasReplaceState && !_.isEqual(params, strippedParams)) {
      var a = document.createElement('a');
      a.href = window.location.href;
      a.search = $.param(strippedParams);

      window.history.replaceState({}, document.title, a.href);
    }
  }
};

r.analytics.breadcrumbs = {
  selector: '.thing, .side, .sr-list, .srdrop, .tagline, .md, .organic-listing, .gadget, .sr-interest-bar, .trending-subreddits, a, button, input',
  maxLength: 3,
  sendLength: 2,

  init: function() {
    this.hasSessionStorage = this._checkSessionStorage();
    this.data = this._load();

    var refreshed = this.data[0] && this.data[0].url == window.location;
    if (!refreshed) {
      this._storeBreadcrumb();
    }

    $(document).delegate('a, button', 'click', $.proxy(function(ev) {
      this.storeLastClick($(ev.target));
    }, this));
  },

  _checkSessionStorage: function() {
    // Via modernizr.com's sessionStorage check.
    try {
      sessionStorage.setItem('__test__', 'test');
      sessionStorage.removeItem('__test__');
      return true;
    } catch(e) {
      return false;
    }
  },

  _load: function() {
    if (!this.hasSessionStorage) {
      return [{stored: false}];
    }

    var data;

    try {
      data = JSON.parse(sessionStorage.breadcrumbs);
    } catch (e) {
      data = [];
    }

    if (!_.isArray(data)) {
      data = [];
    }

    return data;
  },

  store: function() {
    if (this.hasSessionStorage) {
      sessionStorage.breadcrumbs = JSON.stringify(this.data);
    }
  },

  _storeBreadcrumb: function() {
    var cur = {
      url: location.toString(),
    };

    if ('referrer' in document) {
      var referrerExternal = !document.referrer.match('^' + r.config.currentOrigin);
      var referrerUnexpected = this.data[0] && document.referrer != this.data[0].url;

      if (referrerExternal || referrerUnexpected) {
        cur.ref = document.referrer;
      }
    }

    this.data.unshift(cur);
    this.data = this.data.slice(0, this.maxLength);
    this.store();
  },

  storeLastClick: function(el) {
    try {
      this.data[0].click =
        r.utils.querySelectorFromEl(el, this.selector);
      this.store();
    } catch (e) {
      // Band-aid for Firefox NS_ERROR_DOM_SECURITY_ERR until fixed.
    }
  },

  lastClickFullname: function() {
    var lastClick = _.find(this.data, function(crumb) {
      return crumb.click;
    });

    if (lastClick) {
      var match = lastClick.click.match(/.*data-fullname="(\w+)"/);
      return match && match[1];
    }
  },

  toParams: function() {
    params = [];
    for (var i = 0; i < this.sendLength; i++) {
      _.each(this.data[i], function(v, k) {
        params['c' + i + '_' + k] = v;
      });
    }
    return params;
  },

};


// http://stackoverflow.com/a/8809472/704286
r.analytics.uuid = function() {
  var d = new Date().getTime();
  var uuid = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
    var r = (d + Math.random() * 16) % 16 | 0;

    d = Math.floor(d / 16);

    return (c == 'x' ? r : (r & 0x3 | 0x8)).toString(16);
  });

  return uuid;
};


r.analytics.event = {
  init: function() {
    this.contextData = {
      linkFullname: null,
      loid: null,
      srFullname: null,
      srName: null,
      userId: null,
      userName: null,
    };

    if (r.config.user_id) {
      this.contextData.userId = r.config.user_id;
      this.contextData.userName = r.config.logged;
    } else {
      var tracker = new redditlib.Tracker();
      var loggedOutData = tracker.getTrackingData();
      this.contextData.loid = loggedOutData.loid;
    }

    if (r.config.post_site) {
      this.contextData.srName = r.config.post_site;
    }

    if (r.config.cur_site) {
      this.contextData.srFullname = r.config.cur_site;
    }

    if (r.config.cur_link) {
      this.contextData.linkFullname = r.config.cur_link;
    }
  },

  _eventPayload: function() {
    var payload = {};

    if (this.contextData.userId) {
      payload['user_id'] = this.contextData.userId;
      payload['user_name'] = this.contextData.userName;
    } else {
      payload['loid'] = this.contextData.loid;
    }

    if (this.contextData.srName) {
      payload['sr_name'] = this.contextData.srName;
    }

    if (this.contextData.srFullname) {
      payload['sr_id'] = r.utils.fullnameToId(this.contextData.srFullname);
    }

    return payload;
  },

  timeoutForbiddenEvent: function(actionName, actionDetail, targetType, targetFullname) {
    var eventTopic = 'forbidden_actions';
    var eventType = 'cs.forbidden_' + actionName;
    var payload = this._eventPayload();

    payload['process_notes'] = 'IN_TIMEOUT';

    if (actionDetail) {
      payload['details_text'] = actionDetail;
    }

    if (targetType) {
      payload['target_type'] = targetType;
    }

    if (targetFullname) {
      payload['target_fullname'] = targetFullname;
      payload['target_id'] = r.utils.fullnameToId(targetFullname);
    }

    // event collector
    r.events.track(eventTopic, eventType, payload).send();
  },

};
