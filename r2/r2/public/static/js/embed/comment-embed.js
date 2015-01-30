;(function(App, window, undefined) {

  var RE_ABS = /^https?:\/\//i;
  var RE_COMMENT = /\/?r\/[\w_]+\/comments\/(?:[\w_]+\/){2,}[\w_]+\/?/i;
  var PROTOCOL = location.protocol === 'file:' ? 'https:' : '';

  function isComment(anchor) {
    return RE_ABS.test(anchor.href) && RE_COMMENT.test(anchor.pathname);
  }

  function getCommentPathname(anchor) {
    return isComment(anchor) && anchor.pathname.replace(/^\//, '');
  }

  function getCommentUrl(links, host) {
    var pathname;

    for (var i = 0, l = links.length; i < l; i++) {
      if ((pathname = getCommentPathname(links[i]))) {
        break;
      }
    }

    return '//' + host + '/' + pathname;
  }

  function getEmbedUrl(commentUrl, el) {
    var context = 0;
    var showedits = el.getAttribute('data-embed-live');

    if (el.getAttribute('data-embed-parent') === 'true') {
      context++;
    }

    var query = 'embed=' + el.getAttribute('data-embed-token') +
                '&context=' + context +
                '&depth=' + (++context) +
                '&showedits=' + (showedits === 'true') +
                '&created=' + el.getAttribute('data-embed-created') +
                '&showmore=false';

    return PROTOCOL + (commentUrl.replace(/\/$/,'')) + '?' + query;
  }

  App.init = function(options, callback) {
    options = options || {};
    callback = callback || function() {};

    var embeds = document.querySelectorAll('.reddit-embed');

    [].forEach.call(embeds, function(embed) {
      if (embed.getAttribute('data-initialized')) {
        return;
      }

      embed.setAttribute('data-initialized', true);

      var iframe = document.createElement('iframe');
      var anchors = embed.getElementsByTagName('a');
      var commentUrl = getCommentUrl(anchors, embed.getAttribute('data-embed-media'));

      if (!commentUrl) {
        return;
      }

      iframe.height = 0;
      iframe.width = '100%';
      iframe.scrolling = 'no';
      iframe.frameBorder = 0;
      iframe.allowTransparency = true;
      iframe.style.display = 'none';
      iframe.src = getEmbedUrl(commentUrl, embed);

      App.receiveMessageOnce(iframe, 'ping', function(e) {
        embed.parentNode.removeChild(embed);
        iframe.style.display = 'block';

        callback(e);
        App.postMessage(iframe.contentWindow, 'pong', {
          type: 'comment',
          location: location,
          options: options,
        });
      });

      var resizer = App.receiveMessage(iframe, 'resize', function(e) {
        if (!iframe.parentNode) {
          resizer.off();

          return;
        }

        iframe.height = (e.detail + 'px');
      });


      embed.parentNode.insertBefore(iframe, embed);
    });
  };

  App.init();

})((window.rembeddit = window.rembeddit || {}), this);
