/* The ready method */
$(function() {
  var clientTime = Date.now();
  var serverTime = r.config.server_time * 1000;
  var disabledDueToDrift = false;

  // if our server time is more than 5 minutes greater than client time, that
  // means our client clock has future drift. Disable due to hmac signing
  // expiration not being reliable.
  if (serverTime > clientTime + (5 * 60 * 1000)) {
    disabledDueToDrift = true;
  }

  // if our server time is more than 60 minutes in the past, that means our
  // client clock has drift or this whole page has been cached for more than
  // an hour. Disable due to hmac signing expiration not being reliable.
  if (serverTime < clientTime - (60 * 60 * 1000)) {
    disabledDueToDrift = true;
  }

  function setOutboundURL(elem) {
    /* send outbound links to outbound url when clicked */
    var $elem = $(elem);
    var now = Date.now();

    // If our outbound link has not expired, use it.
    if (!disabledDueToDrift && $elem.attr('data-outbound-expiration') > now) {
      elem.href = $elem.attr('data-outbound-url');
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
