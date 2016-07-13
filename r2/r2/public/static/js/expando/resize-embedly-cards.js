!function(r, undefined) {
  /*
    Resize Embedly Cards

    Embedly cards have unknown heights at render time, so we need to wait for
    their contents to load and resize the embed iframe.  Embedly cards use
    a special template (EmbedlyCardMediaEmbedBody) that includes code to pass
    messages (via postMessage) to the parent window containing the correct
    dimensions.

    This is all borrowed from liveupdate and works the same way as there.  If
    we end up implementing this permanently, it should be adjusted so both
    can share the same code.
  */

  $(window).on('message', function(e) {
    var ev = e.originalEvent;

    if (ev.origin.replace(/^https?:\/\//,'') !== r.config.media_domain) {
      return false;
    }

    var data = JSON.parse(ev.data);
    var $embedFrame = $('[id^=media-embed-' + data.updateId + ']');

    if (!$embedFrame.hasClass('embedly-card-embed')) {
      return false;
    }

    if (data.action === 'dimensionsChange') {
      $embedFrame.attr(
        {
          height: data.height,
        }
      );
    }
  });
}(r);
