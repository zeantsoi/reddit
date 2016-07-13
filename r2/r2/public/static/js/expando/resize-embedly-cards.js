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

  var MESSAGE_NAME = 'embedlyCard';

  $(window).on('message', function(e) {
    var ev = e.originalEvent;

    if (ev.origin.replace(/^https?:\/\//,'') !== r.config.media_domain) {
      return false;
    }

    try {
      var message = JSON.parse(ev.data);
    } catch (e) {
      return;
    }

    if (message.name !== MESSAGE_NAME) {
      return;
    }

    var $embedFrame = $('[id^=media-embed-' + message.updateId + ']');

    if (!$embedFrame.hasClass('embedly-card-embed')) {
      return false;
    }

    if (message.action === 'dimensionsChange') {
      $embedFrame.attr(
        {
          height: message.height,
        }
      );
    }
  });
}(r);
