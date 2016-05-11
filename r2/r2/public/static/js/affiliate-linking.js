/* The ready method */
$(function() {

  function setAffiliateURL(elem) {
    var $elem = $(elem);

    elem.href = $elem.attr('data-affiliate-url');

    return true;
  }

  function unaffiliateURL(elem) {
    /* after clicking outbound link, reset url for clean mouseover view */
    elem.href = $(elem).attr('data-href-url');
    return true;
  }

  /* mouse click */
  $("a.affiliate").on('mousedown', function(e) {
    // if right click (context menu), don't show redirect url
    if (e.which === 3) {
      return true;
    }
    return setAffiliateURL(this);
  });

  $("a.affiliate").on('mouseleave', function() {
    return unaffiliateURL(this);
  });

  /* keyboard nav */
  $("a.affiliate").on('keydown', function(e) {
    if (e.which === 13) {
      setAffiliateURL(this);
    }
    return true;
  });

  $("a.affiliate").on('keyup', function(e) {
    if (e.which === 13) {
      unaffiliateURL(this);
    }
    return true;
  });

  /* touch device click */
  $("a.affilate").on('touchstart', function() {
    return setAffiliateURL(this);
  });
});
