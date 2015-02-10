;(function(App, window, undefined) {
  App.VERSION = '0.1';

  var RE_HOST = /^https?:\/\/([^\/|?]+).*/;
  var config = window.REDDIT_EMBED_CONFIG;
  var thing = config.thing;

  if (document.referrer && document.referrer.match(RE_HOST)) {
    App.addPostMessageOrigin(RegExp.$1);
  }

  function checkHeight() {
    var height = document.body.clientHeight;

    if (height && App.height !== height) {
      App.height = height;

      App.postMessage(window.parent, 'resize', height, '*');
    }
  }

  function createPayloadFactory(location) {
    return function payloadFactory(type, action, payload) {
      var now = new Date();
      var data = {
        'event_topic': 'embed',
        'event_name': 'embed_' + action,
        'event_ts': now.getTime(),
        'event_ts_utc_offset': now.getTimezoneOffset() / -60,
        'user_agent': navigator.userAgent,
        'embed_ts_created': config.created,
        'sr_id': thing.sr_id,
        'sr_name': thing.sr_name,
        'embed_id': thing.id,
        'embed_version': App.VERSION,
        'embed_type': type,
        'embed_control': config.showedits,
        'embed_host_url': location.href,
        'comment_edited': thing.edited,
        'comment_deleted': thing.deleted,
      };
  
      for (var name in payload) {
        data[name] = payload[name];
      }
  
      return data;
    };
  }

  setInterval(checkHeight, 100);

  App.receiveMessage(window.parent, 'pong', function(e) {
    var type = e.detail.type;
    var options = e.detail.options;
    var location = e.detail.location;
    var createPayload = createPayloadFactory(location);

    if (options.track === false) {
      return;
    }

    var tracker = new App.PixelTracker({
      url: config.eventtracker_url,
    });

    tracker.send(createPayload(type, 'view'));
  
    function trackLink(e) {
      var el = this;
      var base = document.getElementsByTagName('base');
      var target = el.target || (base && base[0] && base[0].target);
      var newTab = target === '_blank';
      var payload = {
        'redirect_url': el.href,
        'redirect_type': el.getAttribute('data-redirect-type'),
        'redirect_dest': el.host,
        'redirect_thing_id': el.getAttribute('data-redirect-thing'),
      };

      tracker.send(createPayload(type, 'click', payload), function() {
        if (!newTab) {
          window.top.location.href = el.href;
        }
      });

      return newTab;
    }

    var trackLinks = document.getElementsByTagName('a');

    for (var i = 0, l = trackLinks.length; i < l; i++) {
      var link = trackLinks[i];
  
      if (link.getAttribute('data-redirect-type')) {
        trackLinks[i].addEventListener('click', trackLink, false);
      }
    }

  });

  App.postMessage(window.parent, 'ping', {
    config: config,
  });

})((window.rembeddit = window.rembeddit || {}), this);
