r.analytics = {
  init: function() {
    this.onCommentsPage = $('body').hasClass('comments-page');
    this.spotlightIsHidden = $('#siteTable_organic').is(":hidden");
    this.promotedLinkIsHidden = $('.promotedlink.promoted').is(":hidden");
    this.adBlockIsEnabled = this.spotlightIsHidden || this.promotedLinkIsHidden;
    // these guys are relying on the custom 'onshow' from jquery.reddit.js
    $(document).delegate(
      '.promotedlink.promoted',
      'onshow',
      _.bind(function(ev) {
        this.fireTrackingPixel(ev.target);
        r.analytics.bindAdEventPixels();
      }, this)
    );

    // Fires on comment page
    $(document).delegate(
      '.sitetable .promotedlink.promoted',
      'onshow',
      _.bind(function(ev) {
        if (this.onCommentsPage){
          this.fireRetargetingPixel(ev.target);
        }
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

    r.analytics.firePageTrackingPixel(r.analytics.stripAnalyticsParams);
    r.analytics.bindAdEventPixels();

    // Add parameters to track link sharing
    if (r.config.share_tracking_hmac) {
      r.analytics.replaceShareParams();
    }
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

    if (this.onCommentsPage) {
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

    if ($el.data('trackerFired') || this.onCommentsPage) {
      return;
    }

    var pixel = new Image();
    var impPixel = $el.data('impPixel');

    if (impPixel && !this.adBlockIsEnabled) {
      pixel.src = impPixel;
    }

    if (!this.adBlockIsEnabled) {
      var thirdParty = [];
      var linkFullname = $el.data('fullname');
      var campaignFullname = $el.data('cid');
      var pixel1 = $el.data('thirdPartyTrackingUrl');
      var pixel2 = $el.data('thirdPartyTrackingTwoUrl');

      if (pixel1) {
        thirdParty.push(pixel1);
      }

      if (pixel2) {
        thirdParty.push(pixel2);
      }

      if (thirdParty.length) {

        thirdParty.forEach(function(url) {
          r.analytics.thirdPartyPixelAttemptEvent({
            pixel_url: url,
            link_fullname: linkFullname,
            campaign_fullname: campaignFullname,
          });
        });

        r.gtm.trigger('fire-pixels', {
          pixels: thirdParty,
          link_fullname: linkFullname,
          campaign_fullname: campaignFullname,
        });
      }
    }

    var adserverPixel = new Image();
    var adserverImpPixel = $el.data('adserverImpPixel');

    if (adserverImpPixel && !this.adBlockIsEnabled) {
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
    var contextData = r.events.contextData;

    if (!url) {
      return;
    }
    var params = {
      dnt: contextData.dnt,
    };

    if (contextData.loid) {
      params.loid = contextData.loid;
    }
    if (contextData.loid_created) {
      params.loidcreated = decodeURIComponent(contextData.loid_created);
    }

    var querystring = [
      'r=' + Math.random(),
    ];

    if (contextData.referrer_domain) {
      querystring.push(
        'referrer_domain=' + encodeURIComponent(contextData.referrer_domain)
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

  /**
  Fires a retargeting pixel to Adzerk so we could retarget a user
  **/
  fireRetargetingPixel: function(el) {
    var $el = $(el);
    var retargetPixel = new Image();
    var retargetPixelUrl = $el.data('adserverRetargetPixel');

    if (retargetPixelUrl && !this.adBlockIsEnabled) {
      retargetPixel.src = retargetPixelUrl;
    }
  },

  // If we passed along referring tags to this page, after it's loaded, remove them from the URL so that 
  // the user can have a clean, copy-pastable URL. This will also help avoid erroneous analytics if they paste the URL
  // in an email or something.
  stripAnalyticsParams: function() {
    var hasReplaceState = !!(window.history && window.history.replaceState);
    var params = $.url().param();
    var stripParams = ['ref', 'ref_source', 'ref_campaign'];
    // strip utm tags as well
    _.keys(params).forEach(function(paramKey){
      if (paramKey.indexOf('utm_') === 0){
        stripParams.push(paramKey);
      }
    });

    var strippedParams = _.omit(params, stripParams);
    // Add parameters to track link sharing if 'st' and 'sh'
    // are not present in the existing params. If they're present,
    // updating them would leave multiple entries in browser history
    if (r.config.share_tracking_hmac && !('st' in params || 'sh' in params)) {
      _.extend(strippedParams, r.analytics.replaceShareParams());
    }

    if (hasReplaceState && !_.isEqual(params, strippedParams)) {
      var a = document.createElement('a');
      a.href = window.location.href;
      a.search = $.param(strippedParams);

      window.history.replaceState({}, document.title, a.href);
    }

  },

  replaceShareParams: function() {
    var shareParams = {};
    // Add timestamp (base36) and a signing hash (last 8 digits)
    // to track link sharing.
    shareParams["st"] = r.config.share_tracking_ts.toString(36);
    shareParams["sh"] = r.config.share_tracking_hmac.substring(0, 8);

    return shareParams;
  },

  adServingEvent: function(eventType, payload) {
    var eventTopic = 'ad_serving_events';
    var eventType = 'cs.' + eventType;

    r.events.track(eventTopic, eventType, payload, {
      contextProperties: [
        'referrer_domain',
        'referrer_url',
        'adblock',
        'dnt',
        'sr_name',
        'sr_id',
        'listing_name',
        'page_type',
      ],
    });
  },

  _thirdPartyPixelEvent: function(eventType, payload) {
    payload = payload || {};

    if (payload.pixel_url) {
      var parser = document.createElement('a');
      parser.href = payload.pixel_url;

      payload.pixel_domain = parser.host;
    }

    return this.adServingEvent(eventType, payload);
  },

  thirdPartyPixelAttemptEvent: function(payload) {
    return this._thirdPartyPixelEvent(
      'third_party_impression_pixel_attempt',
      payload
    );
  },

  thirdPartyPixelFailureEvent: function(payload) {
    return this._thirdPartyPixelEvent(
      'third_party_impression_pixel_failure',
      payload
    );
  },

  thirdPartyPixelSuccessEvent: function(payload) {
    return this._thirdPartyPixelEvent(
      'third_party_impression_pixel_success',
      payload
    );
  },

  adblockEvent: function(placementType, payload) {
    var payload = payload || {};

    payload.placement_type = placementType;

    return this.adServingEvent('adblock', payload);
  },

  adsInteractionEvent: function(action, payload, done) {
    var eventTopic = 'selfserve_events';
    var eventType = 'cs.interaction.' + action;

    r.events.track(eventTopic, eventType, payload, {
      contextProperties: [
        'referrer_domain',
        'referrer_url',
      ],
    });

    if (done) {
      r.events.send(done);
    }
  },

  loginRequiredEvent: function(actionName, actionDetail, targetType, targetFullname) {
    var eventTopic = 'login_events';
    var eventType = 'cs.loggedout_' + actionName;
    var payload = {};

    payload['process_notes'] = 'LOGIN_REQUIRED';

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
    r.events.track(eventTopic, eventType, payload, {
      contextProperties: [
        'sr_name',
        'sr_id',
        'listing_name',
        'referrer_domain',
        'referrer_url',
      ],
    }).send();
  },

  timeoutForbiddenEvent: function(actionName, actionDetail, targetType, targetFullname) {
    var eventTopic = 'forbidden_actions';
    var eventType = 'cs.forbidden_' + actionName;
    var payload = {};

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
    r.events.track(eventTopic, eventType, payload, {
      contextProperties: [
        'sr_name',
        'sr_id',
      ],
    }).send();
  },

  imageUploadEvent: function(mimetype, size, source, key, unsuccessful) {
    var eventTopic = 'image_upload_events';
    var eventType = 'cs.upload_image';
    var payload = {};

    if (unsuccessful) {
      payload['process_notes'] = unsuccessful;
    } else {
      payload['successful'] = true;
    }

    if (mimetype) {
      payload['image_mimetype'] = mimetype;
    }

    if (size) {
      payload['image_size'] = size;
    }

    if (source) {
      payload['image_source'] = source;
    }

    if (key) {
      payload['image_key'] = key;
    }

    // event collector
    r.events.track(eventTopic, eventType, payload, {
      contextProperties: [
        'referrer_domain',
        'referrer_url',
        'sr_name',
        'sr_id',
      ],
    }).send();
  },

  registerAdvanceEvent: function(email) {
    // An event that is fired when an email is entered into the 
    // email field in the experiment.
    var eventTopic = 'login_events';
    var eventType = 'cs.register_step_advance';
    var payload = {};

    payload['step_name'] = 'enter_email';
    payload.email = email;

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
      
    }

    if ('provider' in targetData) {
      payload['provider'] = targetData.provider;
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

    r.events.track(eventTopic, eventType, payload, {
      contextProperties: [
        'page_type',
        'listing_name',
        'referrer_domain',
        'referrer_url',
        'expando_preference',
        'media_preference_hide_nsfw',
      ],
    }).send();
  },

  sendEvent: function(eventTopic, actionName, contextProperties, payload, done) {
    this.queueEvent(eventTopic, actionName, contextProperties, payload).send(done);
  },

  queueEvent: function(eventTopic, actionName, contextProperties, payload) {
    var eventType = 'cs.' + actionName;
    return r.events.track(eventTopic, eventType, payload, {
      contextProperties: contextProperties,
    });
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

