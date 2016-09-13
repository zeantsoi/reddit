!function(r, _, $) {
  /*
  For managing promo requests
  */
  r.promo = {
    _initialized: false,

    setup: function(displayedThings, site, showPromo){
      this.displayedThings = displayedThings;
      this.site = site;
      this.loid = $.cookie('loid');
      this._initialized = true;
      // adCanary to see if promotedlinks are adblocked
      var $adCanary = $('<div />')
                      .addClass('promotedlink')
                      .appendTo($('body'))
                      .show();
      if($('#siteTable_organic').length && $('#siteTable_organic').is(":hidden")) {
        this.adBlockIsEnabled = $adCanary.is(':visible');
      } else {
        this.adBlockIsEnabled = $adCanary.is(':hidden');
      }

      if (this.adBlockIsEnabled) {
        r.analytics.adblockEvent('native-headline', {
          method: 'element-hidden',
        });
      }

      this.showPromo = showPromo && !this.adBlockIsEnabled;
    },

    requestPromo: function(options){
      options = options || {};

      var params = r.utils.parseQueryString(location.search);
      var url = '/api/request_promo';

      if (params.feature) {
        url += '?' + $.param({ feature: params.feature }, true)
      }

      var currentDate = new Date();

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
          day: currentDate.getDay(),
          hour: currentDate.getHours(),
          adblock: r.utils.getAdblockLevel(),
        },
      });
    },
  };
}(r, _, jQuery);
