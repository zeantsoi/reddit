/*
  Init modules defined in reddit-init.js

  requires r.hooks (hooks.js)
 */
!function(r) {
  r.hooks.get('reddit-init').register(function() {
    try {
        r.events.init();
        r.analytics.init();

        if (r.config.feature_scroll_events) {
          r.scrollEvent.init();
        }

        if (r.config.feature_screenview_events) {
          r.screenviewEvent.init();
        }

        r.resEvent.init();
        r.access.init();
    } catch (err) {
        r.sendError('Error during reddit-init.js init', err.toString());
    }
  })

  $(function() {
    r.hooks.get('reddit-init').call();
  });
}(r);
