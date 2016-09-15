!function(r) {
  if (!r.config.feature_flatlist_events) {
    return;
  }

  var EVENT_TOPIC = 'flatlist_events';

  function isTargetInContainer(target, container) {
    return container && $.contains(container, target);
  }

  function sendFlatListEvent(e, cb) {
    var $target = $(e.target);
    var $thing = $target.thing();

    var isValidTarget = (
      e.target &&
      isTargetInContainer(e.target, $thing.children('.entry').find('.flat-list')[0]) ||
      isTargetInContainer(e.target, $('.commentarea > .menuarea')[0])
    );

    if (!isValidTarget) {
      if (typeof cb === 'function') {
        cb();
      }
      return;
    }

    var eventAction = e.eventAction || $target.data('event-action') || e.action;

    if (/^legacy:/.test(eventAction)) {
      return;
    }

    var targetType = $target.data('type') || $.getThingType($thing);
    var targetFullname = $target.data('fullname') || $thing.data('fullname');
    var actionDetail = e.eventDetail || $target.data('event-detail');

    // set target using page context
    if (!targetFullname && targetType == 'subreddit') {
      targetFullname = r.config.cur_site;
    } else if (!targetFullname && targetType == 'link') {
      targetFullname = r.config.cur_link;
    }

    var thingData = $thing.data();

    var defaultFields = [
      'listing_name',
      'language',
      'dnt',
      'referrer_domain',
      'referrer_url',
      'session_referrer_domain',
      'user_in_beta',
    ];

    var actionName = targetType + '_flatlist_click';

    var customFields = {
      process_notes: eventAction,
    };

    if (actionDetail) {
      customFields.details_text = actionDetail;
    }

    if (targetFullname) {
      customFields.target_fullname = targetFullname;
      customFields.target_id = r.utils.fullnameToId(targetFullname);
    }

    if (targetType === 'link') {
      customFields.target_url = $.getLinkURL($thing);;
      
      if ('domain' in thingData) {
        customFields.target_url_domain = thingData.domain;
      }
    }

    if ('timestamp' in thingData) {
      customFields.target_created_ts = thingData.timestamp;
    }

    if ('author' in thingData) {
      customFields.target_author_name = thingData.author;

      if (thingData.author === r.config.logged) {
        customFields.is_target_author = true;
      }
    }

    if ('subreddit' in thingData) {
      customFields.sr_name = thingData.subreddit;
    }

    if ('subredditFullname' in thingData) {
      customFields.sr_id = r.utils.fullnameToId(thingData.subredditFullname);
    }

    if ('canBan' in thingData) {
      customFields.is_target_moderator = true;
    }

    r.analytics.sendEvent(EVENT_TOPIC, actionName, defaultFields, customFields, cb);
  }

  $(function() {
    $(document.body).on('click', '.thing > .entry .bylink', function(e) {
      var eventAction = $(e.target).data('event-action');

      if (!eventAction) { return; }

      e.preventDefault();

      r.actions.trigger('navigate', {
        target: e.target,
        eventAction: eventAction,
      });
    });

    r.actions.on('navigate:success', function(e) {
      sendFlatListEvent(e, function() {
        if (r.config.new_window && $(e.target).hasClass('may-blank')) {
          var newWindow = window.open(e.target.href, '_blank');
          // not really necessary, but for consistency
          newWindow.opener = null;
        } else {
          window.location = e.target.href;
        }
      })
    });
  });

  var flatlistActions = [
    'share',
    'save',
    'legacy:change-state',
    'report',
    'report_list',
    'legacy:big-mod-action',
    'legacy:big-mod-toggle',
    'reply',
    'comment',
    'edit',
    'embed',
    'give-gold',
    'flair',
  ];

  flatlistActions.forEach(function(action) {
    r.actions.on(action + ':success', sendFlatListEvent); 
  });
}(r);
