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

      if(this.showPromo){
        this.insertPromo();
      }

      this._initialized = true;
    },

    insertPromo: function(){
      var newPromo = r.promo.requestPromo();
      var self = this;
      newPromo.pipe(function(promo){
        var numThings = $('.sitetable').find('.thing').length;
        // if too few items displayed, don't display ad
        if(numThings < self.FOLD_LINE){
          return;
        }

        var $sibling = self.getSibling(self.pos);
        if(promo){
          var $item = $(promo);
          // adsense will throw error if inserted while hidden
          if (!$item.hasClass('adsense-wrap')) {
            $item.hide().insertBefore($sibling);
            $item.show();
          } else {
            $item.insertBefore($sibling);
          }
          return $item;
        }
      });
    },

    getSibling: function(pos){
      return $('.sitetable').find('.thing').eq(pos);
    }
  };
}(r, _, jQuery);
