!function(r, _, $) {
  /**
  Function for managing listings.
  Currently only inserts ads into the listing
  */
  r.listing = {
    _initialized: false,
    FOLD_LINE: 6, //the average number of links before the screen fold

    setup: function(displayedThings, site, showPromo, pos){
      this.displayedThings = displayedThings;
      this.site = site;
      this.showPromo = showPromo;
      this.loid = $.cookie('loid');
      this.pos = $.with_default(pos, 0);

      // ensure that r.promo is initialized
      if(!r.promo || !r.promo._initialized){
        r.promo.setup(this.displayedThings, this.site, this.showPromo);
      }

      this.showPromo = showPromo && !r.promo.adBlockIsEnabled;
      if(this.showPromo){
        this.insertPromo();
      }

      this._initialized = true;
    },

    insertPromo: function(){
      var newPromo = r.promo.requestPromo({ placements: 'feed-' + this.pos });
      var self = this;
      newPromo.pipe(function(promo){
        if(!promo || !promo.length) {
          return;
        }

        var numThings = $('.sitetable.linklisting').find('.thing').length;
        // if too few items displayed, don't display ad
        if(numThings < self.FOLD_LINE){
          return;
        }

        var $sibling = self.getSibling(self.pos);
        if(promo){
          var $item = $(promo);
          if (!$item.hasClass('adsense-wrap')) {
            $item.insertBefore($sibling).show();
          }
          return $item;
        }
      }.bind(this), function onError(xhr, statusText) {
        // Ignore http errors/timeouts. A `status` of `0` means
        // the request wasn't actually finished (likely net::ERR_BLOCKED_BY_CLIENT)
        if (statusText === 'timeout' || xhr.status !== 0) {
          return;
        }

        r.analytics.adblockEvent('native-headline', {
          method: 'endpoint-blocked',
          in_feed: true,
        });
      });
    },

    getSibling: function(pos){
      return $('.sitetable').find('.thing').eq(pos);
    }
  };

  var loadMoreListings = function(count){
    $.ajax({
      method: 'GET',
      url: location.pathname,
      data: {'count': count, 'after': $('.thing.link').last().data('fullname')},
      success: function(results){
        displayResults(results, count);
      }
    });
  };

  var displayResults = function(results, count) {
    var linkHtml = $.parseHTML(results);
    var listings = $(linkHtml).find('.thing.link');

    $.each(listings, function(i,link){
      $(adjustRankWidth(link, count)).insertAfter('#siteTable .thing:last');
    });
  };

  var updateNextPrevButtons = function(){
    // checking for RES here instead of on $(document).ready to give RES time
    // to be applied to DOM
    if (r.isResActive()){
      return;
    }

    $(document.body).on('click', '.prev-button, .next-button', function(e) {
      if ($(this).hasClass('prev-button')){
        var $firstLink = $('#siteTable .thing.link').first();
        var firstId = $firstLink.data('fullname');
        var firstRank = $firstLink.data('rank');
        // prev button will NOT lazy load. instead it will just load previous 100 listings
        $('.prev-button a').attr('href', location.pathname + '?count=' + firstRank + '&before=' + firstId + '&limit=100');
      } else if ($(this).hasClass('next-button')){
        var $lastLink = $('#siteTable .thing.link').last();
        var lastId = $lastLink.data('fullname');
        var count = $lastLink.data('rank');
        $('.next-button a').attr('href', location.pathname + '?count=' + count + '&after=' + lastId);
      }
    });
  };

  var lazyLoadOnScroll = function(){
    // checking for RES here instead of on $(document).ready to give RES time
    // to be applied to DOM
    if (r.isResActive()){
      return;
    }

    var urlCount = parseInt($.url().param('count'), 10) || 0;
    var loadPoint = 3; // load more links when the 3rd link hits the top of the viewport
    var data = {
      'urlCount': urlCount,
      'linkCount': urlCount + 25,
      'prevLinkCount': 0,
      'loadPoint': loadPoint,
      'fromPrevButton': !!$.url().param('before'),
      'middleOfPage': getMiddleOfPage(loadPoint),
    }
    $(window).on('scroll', null, data, doLoad);
  };

  doLoad = function(event){
      var d = event.data;
      var topOfPage = $(window).scrollTop();

      if (d.middleOfPage &&
          topOfPage > d.middleOfPage &&
          d.prevLinkCount !== d.linkCount &&
          // if we navigated to this page via "previous" button, don't do lazy load
          !d.fromPrevButton){
        loadMoreListings(d.linkCount);
        d.prevLinkCount = d.linkCount;
        d.linkCount += 25;
        d.loadPoint += 20; // load more links once you have navigated 20 more links down the page
        d.middleOfPage = getMiddleOfPage(d.loadPoint);
      }

      if (d.linkCount >= d.urlCount + 100){ // stop loading when we've hit 100 links
        $(window).off('scroll', doLoad);
      }
  };

  getMiddleOfPage = function(loadPoint){
    // find 'middle' of page (where we want to lazy load more links)
    // not really the middle -- more like upper fourth of page
    var $offset = $('#siteTable .thing:nth-child(' + loadPoint + ')').first().offset();
    if (!$offset) {
      return null
    }
    return $offset.top;
  };

  adjustRankWidth = function(link, count){
    // determines width of rank --> this is determined server side, normally,
    // but with lazy load, we need to alter the width client-side so the numbers
    // don't get cut off on render. This takes care of all numbers up to six
    // digits
    var rank = $(link).find('.rank')
    if (count < 900){
      $(rank).width(27);
    } else if (count < 9900){
      $(rank).width(37);
    } else {
      $(rank).width(47);
    }
    return link;
  };

  $(document).ready(function(){
    if (r.config.feature_lazy_load_listings){
      var urlCount = parseInt($.url().param('count'), 10) || 0;
      $('#siteTable .thing.link .rank').width(adjustRankWidth(this, urlCount));
      updateNextPrevButtons();
      lazyLoadOnScroll();
    }
  })

}(r, _, jQuery);
