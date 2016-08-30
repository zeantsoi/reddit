!function(r, _, $) {
  /*
  For managing promo requests
  */
  r.promo = {
    _initialized: false,

    setup: function(displayedThings, site, showPromo){
      this.displayedThings = displayedThings;
      this.site = site;
      this.showPromo = showPromo;
      this.loid = $.cookie('loid');
      this._initialized = true;
    },

    requestPromo: function(options){
      options = options || {};

      var params = r.utils.parseQueryString(location.search);
      var url = '/api/request_promo';

      if (params.feature) {
        url += '?' + $.param({ feature: params.feature }, true)
      }

      return $.ajax({
        type: 'POST',
        url: url,
        timeout: r.config.ads_loading_timeout_ms,
        data: {
          site: this.site,
          r: r.config.post_site,
          dt: this.displayedThings,
          loid: this.loid,
          is_refresh: options.refresh,
          placements: options.placements,
          referrer: document.referrer,
        },
      });
    },
  };
}(r, _, jQuery);
