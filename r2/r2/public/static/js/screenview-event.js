!function() {
  var EVENT_TOPIC = 'screenview_events';
  var EVENT_TYPE = 'screenview';

  r.screenviewEvent = {
    getDefaultEventFields: function() {
      return [
        'sr_name',
        'sr_id',
        'listing_name',
        'language',
        'dnt',
        'referrer_domain',
        'referrer_url',
        'session_referrer_domain',
        'user_in_beta',
        'adblock',
      ];
    },

    getCustomEventFields: function() {
      var customFields = {
        screen_width: window.screen.width,
        screen_height: window.screen.height,
      };

      var globalEventTarget = r.config.event_target;
      if (globalEventTarget) {
        for (var key in globalEventTarget) {
          var value = globalEventTarget[key];
          if (value !== null) {
            customFields[key] = value;
          }
        }
      }

      var linkListingData = this._getLinkListingContextData();
      if (linkListingData) {
        for (var key in linkListingData) {
          customFields[key] = linkListingData[key];
        }
      }

      return customFields;
    },

    init: function() {
      var defaultFields = this.getDefaultEventFields();
      var customFields = this.getCustomEventFields();

      r.analytics.sendEvent(EVENT_TOPIC, EVENT_TYPE, defaultFields, customFields);
    },

    _getLinkListingContextData: function() {
      var linkListing = [];
      var minRank = null;
      var maxRank = 0;
      
      $('.linklisting .thing.link').each(function() {
          var $thing = $(this);
          var fullname = $thing.data('fullname');
          var rank = parseInt($thing.data('rank')) || '';
          linkListing.push(fullname);
          maxRank = Math.max(maxRank, rank);
          if (minRank == null) {
              minRank = rank;
          }
          minRank = Math.min(minRank, rank);
      });

      if (!_.isEmpty(linkListing)) {
        return {
          link_listing: linkListing,
          link_listing_min_rank: minRank,
          link_listing_max_rank: maxRank,
        };
      }

      return null;
    },
  };
}(r);
