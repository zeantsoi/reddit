!function(r, _, $) {
  /**
  Function for managing listings.
  Currently only inserts ads into the listing
  */
  r.listing = {
    _initialized: false,
    setup: function(displayedThings, site, showPromo){
      this.displayedThings = displayedThings;
      this.site = site;
      this.showPromo = showPromo;
      this.loid = $.cookie('loid');

      // ensure that r.promo is initialized
      if(!r.promo || !r.promo._initialized){
        r.promo.setup(this.displayedThings, this.site, this.showPromo);
      }

      if(this.showPromo){
        this.insertPromo();
      }

      this._initialized = true;
    },

    insertPromo: function(){
      var FOLD_LINE = 6; //the average number of links before the screen fold
      var newPromo = r.promo.requestPromo();
      newPromo.pipe(function(promo){
        var numThings = $(".sitetable").find(".thing").length;
        // if too few items displayed, don't display ad
        if(numThings < FOLD_LINE){
          return;
        }
        var randomInt = Math.floor(Math.random() * FOLD_LINE); // randomInt[0,5]
        var randomSibling = $(".sitetable").find('.thing').eq(randomInt);
        if(promo){
          var $item = $(promo);
          var isHouse = $item.data('house');
          // adsense will throw error if inserted while hidden
          if (!$item.hasClass('adsense-wrap')) {
            $item.hide().insertAfter(randomSibling);
            $item.show();
          } else {
            $item.insertAfter(randomSibling);
          }
          return $item;
        }
      });
    }
  };
}(r, _, jQuery);
