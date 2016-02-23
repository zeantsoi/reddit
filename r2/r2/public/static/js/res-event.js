!function(r, undefined) {
  var EVENT_TOPIC = 'RES_events';
  var EVENT_TYPE = 'RES_session';

  var SESSION_KEY = ['plugin.RES.event', EVENT_TOPIC, EVENT_TYPE].join('/');

  function isResNightmodeEnabled() {
    return !!store.safeGet('RES_nightMode');
  }

  r.hooks.get('analytics').register(function() {
    try {
      // r.syncedSessionStorage may throw if storage is unavailable or disabled
      if (!r.isResActive() || r.syncedSessionStorage.getItem(SESSION_KEY)) {
        return;
      }
    } catch (err) {
      return;
    }

    var defaultFields = [
      'dnt',
    ];

    var customFields = {
      night_mode: isResNightmodeEnabled(),
    };

    r.analytics.sendEvent(EVENT_TOPIC, EVENT_TYPE, defaultFields, customFields);
    r.syncedSessionStorage.setItem(SESSION_KEY, true);
  });
}(r);
