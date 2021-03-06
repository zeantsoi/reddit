/* The ready method */
$(function() {
  var clientTime = Date.now();
  var serverTime = r.config.server_time * 1000;
  var disabledDueToDrift = false;
  var beaconsEnabled = r.config.feature_outbound_beacons && 'sendBeacon' in window.navigator;

  // If the browser supports beacons, we set the outbound URL
  // here on mousedown or other navigate action. Then, before navigate
  // we will send a beacon derived from this element. On mouseup we clear
  // this field.
  var beaconURL = null;

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
    // log outbound clicks, either through redirect or beacon
    var $elem = $(elem);
    var now = Date.now();

    // If our outbound link has not expired, use it.
    if (!disabledDueToDrift && $elem.attr('data-outbound-expiration') > now) {
      if (beaconsEnabled) {
        beaconURL = $elem.attr('data-outbound-url');
      } else {
        elem.href = $elem.attr('data-outbound-url');
      }
    }

    return true;
  }

  function resetOriginalURL(elem) {
    /* after clicking outbound link, reset url for clean mouseover view */
    if (beaconsEnabled) {
      beaconURL = null;
    } else {
      elem.href = $(elem).attr('data-href-url');
    }
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
    // If ctrl (17) + click was used, reset the url
    // when ctrl has been released, so that a user
    // can copy the correct link without leaving
    if (e.which === 13 || e.which === 17) {
      resetOriginalURL(this);
    }
    return true;
  });

  /* touch device click */
  $("a.outbound").on('touchstart', function() {
    return setOutboundURL(this);
  });

  $(window).on('unload', function() {
    if (beaconsEnabled && beaconURL !== null) {
      // For the clicktracker, a GET to the tracking URL (with query parameters) will
      // perform a redirect to the destination. A POST to the same url (with query
      // parameters as payload) will return a 204 No Content (to support beacons).
      // So we take our redirect URL and split it into a POST of the query parameters
      var tempA = $('<a>', {href: beaconURL})[0];
      var beaconPath = tempA.protocol + '//' + tempA.hostname + tempA.pathname;
      var beaconPayload = tempA.search.replace(/^\?/, '');

      navigator.sendBeacon(beaconPath, beaconPayload);
    }
  });
});
