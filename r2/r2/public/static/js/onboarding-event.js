!function(r) {
  var EVENT_TOPIC = "onboarding_events";

  var preselectedCategories = null;

  r.onboardingEvent = {
    init: function() {
      r.actions.on('onboarding:submit', interestGroupsSelectedEvent);
      r.actions.on('onboarding:default', skipOnboardingEvent);
      r.actions.on('onboarding:close', function(event) {
        if (event.skippedOnboarding) {
          skipOnboardingEvent(event);
        }
      });
      r.actions.on('onboarding:preselect', function(event) {
        preselectedCategories = event.categories;
      });
    },
  };

  function sendEvent(eventType, payload) {
    r.analytics.sendEvent(EVENT_TOPIC, eventType, null, payload);
  }

  function interestGroupsSelectedEvent(event) {
    sendEvent('interest_groups_selected', {
      'preselected_interest_groups': preselectedCategories,
      'interest_groups': event.selectedCategories,
    });
  }

  function skipOnboardingEvent(event) {
    sendEvent('skip_onboarding', {
      'preselected_interest_groups': preselectedCategories,
    });
  };
}(window.r);
