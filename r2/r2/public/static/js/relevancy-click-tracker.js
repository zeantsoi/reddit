!(function(r) {
  var EVENT_TOPIC = 'internal_click_events';
  var EXPERIMENT_NAME = 'relevancy_sidebar';

  function pick(obj, predicate) {
    var copy = {};
    for (var k in obj) {
      var val = obj[k];
      if (predicate(val)) {
        copy[k] = val;
      }
    }
    return copy;
  }

  function trackInternalClicks(experimentName) {
    return function(e) {
      e.preventDefault();
      var $currentTarget = $(e.currentTarget);
      var url = $currentTarget.attr('href')
      var eventType = $currentTarget.data('event_type');

      var defaultFields = ['referrer_url'];

      // don't send fields that have empty string values
      var customFields = pick({
        experiment_name: experimentName,
        referrer_page_type: $currentTarget.data('page_type'),
        link_index: $currentTarget.index(),
        target_url: $currentTarget.attr('href'),
        target_type: $currentTarget.data('target_type'),
        link_name: $currentTarget.data('link_name'),
        target_name: $currentTarget.data('target_name'),
        target_fullname: $currentTarget.data('target_fullname'),
      }, function(v) {
        return v !== "";
      });

      if (customFields.target_fullname) {
        customFields['target_id'] = r.utils.fullnameToId(customFields.target_fullname);
      }

      r.analytics.sendEvent(EVENT_TOPIC, eventType, defaultFields, customFields, function() {
        // only update the url if the login modal doesn't show
        if (!$currentTarget.hasClass('login-required')) {
          // We're cognizant of and accept the fact that this breaks expected
          // browser behavior just for the sake of this experiment.
          window.location.href = url;
        }
      });
    }
  }

  ['.posts-divider a', '.sub-bar a', '.posts-carousel a'].forEach(function(selector) {
    $(selector).on('click', trackInternalClicks('top_posts'));
  });
})(r);
