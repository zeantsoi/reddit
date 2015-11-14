!(function(global, r, $, undefined) {
  var COOKIE_MESSAGE = _.escape(r._('Cookies help us deliver our Services. By using our Services or clicking I agree, you agree to our use of cookies.'));

  var required = r.config.requires_eu_cookie_policy;
  var cookie = r.config.eu_cookie;
  var maxAttempts = r.config.eu_cookie_max_attempts;
  var shown = parseInt($.cookie(cookie) || 0, 10);

  if (required && shown < maxAttempts) {
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

          $.cookie(cookie, maxAttempts);

          $(this).hide();
        })
    );

    $.cookie(cookie, Math.min(shown + 1, maxAttempts));
  }

})(this, (this.r = this.r || {}), this.jQuery);
