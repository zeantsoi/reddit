r.analytics = {
  init: function() {
    // these guys are relying on the custom 'onshow' from jquery.reddit.js
    $(document).delegate(
      '.organic-listing .promotedlink.promoted',
      'onshow',
      _.bind(function(ev) {
        this.fireTrackingPixel(ev.target);
        r.analytics.bindAdEventPixels();
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

    r.analytics.contextData = {
      doNotTrack: window.DO_NOT_TRACK,
      language: document.getElementsByTagName('html')[0].getAttribute('lang'),
      linkFullname: r.config.cur_link || null,
      loid: null,
      loidCreated: null,
      referrer: document.referrer || '',
      referrerDomain: null,
      srFullname: r.config.cur_site || null,
      srName: r.config.post_site || null,
      userId: null,
      userName: null,
    };

    if (r.config.user_id) {
      r.analytics.contextData.userId = r.config.user_id;
      r.analytics.contextData.userName = r.config.logged;
    } else {
      var tracker = new redditlib.Tracker();
      var loggedOutData = tracker.getTrackingData();
      if (loggedOutData && loggedOutData.loid) {
        r.analytics.contextData.loid = loggedOutData.loid;
        if (loggedOutData.loidcreated) {
          r.analytics.contextData.loidCreated = loggedOutData.loidcreated;
        }
      }
    }

    if (document.referrer) {
      var referrerDomain = document.referrer.match(/\/\/([^\/]+)/);
      if (referrerDomain && referrerDomain.length > 1) {
        r.analytics.contextData.referrerDomain = referrerDomain[1];
      }
    }

    if ($('body').hasClass('comments-page')) {
      r.analytics.contextData.pageType = 'comments';
    } else if ($('body').hasClass('listing-page')) {
      r.analytics.contextData.pageType = 'listing';

      if (r.config.cur_listing) {
        r.analytics.contextData.listingName = r.config.cur_listing;
      }
    }

    if (r.config.feature_screenview_events) {
      r.analytics.screenviewEvent();
    }

    r.analytics.firePageTrackingPixel(r.analytics.stripAnalyticsParams);
    r.analytics.bindAdEventPixels();
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

  bindAdEventPixels: function() {
    var $el = $('.link.promoted');

    if (!$el.length) {
      return;
    }

    var onCommentsPage = $('body').hasClass('comments-page');
    var thingId = $el.thing_id();
    var adserverUpvotePixel, adserverDownvotePixel;

    function setEventPixel(eventName, pixel) {
      var key = 'ads.' + eventName;
      var pixels = (store.safeGet(key) || {});
      var recentAds = (store.safeGet('ads.recent') || []);

      // ensure this doesn't get too big
      if (recentAds.length > 2) {
        var removeThing = recentAds.pop();
        delete pixels[removeThing];
      }

      pixels[thingId] = pixel;
      recentAds.push(thingId);
      recentAds = _.unique(recentAds);

      store.safeSet(key, pixels);
      store.safeSet('ads.recent', recentAds);
    }

    function getEventPixel(eventName) {
      var key = 'ads.' + eventName;
      return (store.safeGet(key) || {})[thingId];
    }

    if (onCommentsPage) {
      adserverUpvotePixel = getEventPixel('adserverUpvotePixel');
      adserverDownvotePixel = getEventPixel('adserverDownvotePixel');
    } else {
      adserverUpvotePixel = $el.data('adserverUpvotePixel');
      adserverDownvotePixel = $el.data('adserverDownvotePixel');

      // store in localStorage in case the user nagivates to the comments
      // and then decides to vote
      setEventPixel('adserverUpvotePixel', adserverUpvotePixel);
      setEventPixel('adserverDownvotePixel', adserverDownvotePixel);
    }

    if (adserverUpvotePixel) {
      $el.on('click', '.arrow.up', function() {
        var pixel = new Image();
        pixel.src = adserverUpvotePixel;
      });
    }

    if (adserverDownvotePixel) {
      $el.on('click', '.arrow.down', function() {
        var pixel = new Image();
        pixel.src = adserverDownvotePixel;
      });
    }

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

    var adserverPixel = new Image();
    var adserverImpPixel = $el.data('adserverImpPixel');

    if (adserverImpPixel && !adBlockIsEnabled) {
      adserverPixel.src = adserverImpPixel;
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

  firePageTrackingPixel: function(callback) {
    var url = r.config.tracker_url;
    if (!url) {
      return;
    }
    var params = {
      dnt: this.contextData.doNotTrack,
    };

    if (this.contextData.loid) {
      params.loid = this.contextData.loid;
    }
    if (this.contextData.loidCreated) {
      params.loidcreated = this.contextData.loidCreated;
    }

    var querystring = [
      'r=' + Math.random(),
    ];

    if (this.contextData.referrerDomain) {
      querystring.push(
        'referrer_domain=' + encodeURIComponent(this.contextData.referrerDomain)
      );
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
  },

  screenviewEvent: function() {
    var eventTopic = 'screenview_events';
    var eventType = 'cs.screenview';
    var payload = {};

    if (this.contextData.userId) {
      payload['user_id'] = this.contextData.userId;
      payload['user_name'] = this.contextData.userName;
    } else {
      payload['loid'] = this.contextData.loid;
      payload['loid_created'] = this.contextData.loidCreated;
    }

    if (this.contextData.srName) {
      payload['sr_name'] = this.contextData.srName;
    }
    if (this.contextData.srFullname) {
      payload['sr_id'] = r.utils.fullnameToId(this.contextData.srFullname);
    }

    if (this.contextData.listingName) {
      payload['listing_name'] = this.contextData.listingName;
    }

    if (this.contextData.referrer) {
      payload['referrer_url'] = this.contextData.referrer;
    }
    if (this.contextData.referrerDomain) {
      payload['referrer_domain'] = this.contextData.referrerDomain;
    }

    payload['language'] = this.contextData.language;
    payload['dnt'] = this.contextData.doNotTrack;

    if (r.config.event_target) {
      for (var key in r.config.event_target) {
        var value = r.config.event_target[key];
        if (value !== null) {
          payload[key] = value;
        }
      }
    }

    // event collector
    r.events.track(eventTopic, eventType, payload).send();
  },

  timeoutForbiddenEvent: function(actionName, actionDetail, targetType, targetFullname) {
    var eventTopic = 'forbidden_actions';
    var eventType = 'cs.forbidden_' + actionName;
    var payload = {};

    payload['process_notes'] = 'IN_TIMEOUT';

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

  expandoEvent: function(actionName, targetData) {
    if (!r.config.feature_expando_events) { return; }

    var eventTopic = 'expando_events';
    var eventType = 'cs.' + actionName;
    var payload = {};

    if ('linkIsNSFW' in targetData) {
      payload['nsfw'] = targetData.linkIsNSFW;
    }

    if ('linkType' in targetData) {
      payload['target_type'] = targetData.linkType;
      
      if (targetData.linkType === 'self' ||
          targetData.linkDomain === r.config.cur_domain) {
        // self posts and reddit live embeds
        payload['provider'] = 'reddit';
      } else {
        payload['provider'] = 'embedly';
      }
    }

    if ('linkFullname' in targetData) {
      payload['target_fullname'] = targetData.linkFullname;
      payload['target_id'] = r.utils.fullnameToId(targetData.linkFullname);
    }

    if ('linkCreated' in targetData) {
      payload['target_create_ts'] = targetData.linkCreated;
    }

    if ('linkURL' in targetData) {
      payload['target_url'] = targetData.linkURL;
    }

    if ('linkDomain' in targetData) {
      payload['target_url_domain'] = targetData.linkDomain;
    }

    if ('authorFullname' in targetData) {
      payload['target_author_id'] = r.utils.fullnameToId(targetData.authorFullname);
    }
      
    if ('subredditName' in targetData) {
      payload['sr_name'] = targetData.subredditName;
    }

    if ('subredditFullname' in targetData) {
      payload['sr_id'] = r.utils.fullnameToId(targetData.subredditFullname);
    }

    if (this.contextData.userId) {
      payload['user_id'] = this.contextData.userId;
      payload['user_name'] = this.contextData.userName;
    } else {
      payload['loid'] = this.contextData.loid;
      payload['loid_created'] = this.contextData.loidCreated;
    }

    if (this.contextData.referrer) {
      payload['referrer_url'] = this.contextData.referrer;
    }

    if (this.contextData.referrerDomain) {
      payload['referrer_domain'] = this.contextData.referrerDomain;
    }
    
    if (this.contextData.pageType) {
      payload['page_type'] = this.contextData.pageType;
    }

    if (this.contextData.listingName) {
      payload['listing_name'] = this.contextData.listingName;
    }

    r.events.track(eventTopic, eventType, payload).send();
  },
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


r.hooks.get('setup').register(function() {
  r.analytics.breadcrumbs.init();
});

