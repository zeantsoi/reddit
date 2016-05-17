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
      return $.ajax({
        type: 'POST',
        url: '/api/request_promo',
        timeout: 1000,
        data: {
          site: this.site,
          r: r.config.post_site,
          dt: this.displayedThings,
          loid: this.loid,
          is_refresh: options.refresh,
        },
      });
    },
  };
}(r, _, jQuery);
