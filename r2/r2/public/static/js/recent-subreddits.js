!(function(r, global) {
  'use strict';

  var RECENT_SRS_LIMIT = 10;
  var cookie = $.cookie_read('recent_srs');

  if (!cookie.data) {
    cookie.data = [];
  } else {
    cookie.data = cookie.data.split(',');
  }

  if (r.config.cur_site) {
    cookie.data.unshift(r.config.cur_site);
    cookie.data = _.first(_.uniq(cookie.data), RECENT_SRS_LIMIT).join(',');
    cookie.expires = 365 * 10;
    cookie.secure = true;

    $.cookie_write(cookie);
  }

}(this.r = this.r || {}, this));
