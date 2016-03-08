/* The ready method */
$(function() {
  // Log the time this page was rendered so that we can determine if it's been > our expiration time for links. If so,
  // don't use the tracking URLs.
  var startTime = Date.now();

  function setOutboundURL(elem) {
    /* send outbound links to outbound url when clicked */

    // If it's been over an hour since the page was rendered, don't track links as our hmac has expired.
    if (Date.now() - startTime < (60 * 60 * 1000)) {
      elem.href = $(elem).attr('data-outbound-url');
    }

    return true;
  }

  function resetOriginalURL(elem) {
    /* after clicking outbound link, reset url for clean mouseover view */
    elem.href = $(elem).attr('data-href-url');
    return true;
  }

  /* mouse click */
  $("a.outbound").on('mousedown', function(e) {
    // if right click (context menu), don't show redirect url
    if (e.which === 3) {
      return true;
    }
    return setOutboundURL(this);
  });

  $("a.outbound").on('mouseleave', function() {
    return resetOriginalURL(this);
  });

  /* keyboard nav */
  $("a.outbound").on('keydown', function(e) {
    if (e.which === 13) {
      setOutboundURL(this);
    }
    return true;
  });

  $("a.outbound").on('keyup', function(e) {
    if (e.which === 13) {
      resetOriginalURL(this);
    }
    return true;
  });

  /* touch device click */
  $("a.outbound").on('touchstart', function() {
    return setOutboundURL(this);
  });
});
