!(function(global, r, $, undefined) {
  var COOKIE_MESSAGE = _.escape(r._('Cookies help us deliver our Services. By using our Services or clicking I agree, you agree to our use of cookies.'));

  var required = r.config.requires_eu_cookie_policy;
  var maxAttempts = r.config.eu_cookie_max_attempts;

  /**
   * HACK: We accidentally released EU cookies to production setting a cookie
   * on the current path, which meant that it would show up always for
   * different paths. This is bad because the cookie has essentially been
   * made permanently unreliable, such that if we don't know the path that it
   * was set upon we can't clear it or update it.
   *
   * Here we're migrating to a v2 of the cookie, but still reading from the
   * old cookie if it exists so that we don't show it to users if they've
   * already accepted it from the homepage. If they see it this time, it will
   * write to the new cookie and on next page load it will take the new
   * cookie as the preference, which will always be set at the root path.
   *
   * Luckily the eu_cookie will go away over time,  as it was only a session
   * cookie at the time it was set, so probably sometime in early 2016 we can
   * migrate back to just eu_cookie.
  **/
  var oldCookieName = 'eu_cookie';
  var newCookieName = 'eu_cookie_v2';
  var previousTimesShown = parseInt($.cookie(newCookieName) || 0, 10);

  function _setEUCookieValue(value) {
    $.cookie(newCookieName, value, {
      domain: r.config.cur_domain,
      path: '/',
      expires: 365 * 10,
    });
  }

  if (!previousTimesShown) {
    previousTimesShown = parseInt($.cookie(oldCookieName) || 0, 10);

    // Copy the current value to the new cookie location regardless
    // of the state.
    if (previousTimesShown) {
      _setEUCookieValue(previousTimesShown);
    }
  }

  if (required && previousTimesShown < maxAttempts) {
    $(document.body).append(
        $('<form id="eu-cookie-policy">' +
            '<div class="reddit-infobar md-container-small with-icon with-btn cookie-infobar">' +
              '<div class="md">' +
                  '<p>' +
                    COOKIE_MESSAGE +
                    '&nbsp;' +
                    '&nbsp;' +
                    '<a href="https://www.reddit.com/help/privacypolicy">' +
                      _.escape(r._('Learn More')) +
                    '</a>' +
                  '</p>' +
              '</div>' +
              '<div class="infobar-btn-container">' +
                '<button class="c-btn c-btn-primary" type="submit">' +
                  _.escape(r._('I AGREE')) +
                '</button>' +
              '</div>' +
            '</div>' +
          '</form>'
        ).on('submit', function(e) {
          e.preventDefault();

          _setEUCookieValue(maxAttempts);

          $(this).hide();
        })
    );

    _setEUCookieValue(Math.min(previousTimesShown + 1, maxAttempts));
  }

})(this, (this.r = this.r || {}), this.jQuery);
