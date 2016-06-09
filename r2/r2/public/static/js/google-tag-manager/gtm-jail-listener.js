;(function(global, r, undefined) {
  var jail = document.createElement('iframe');
  var queue = [];
  var preload = r.frames.receiveMessage('*.gtm', function(e) {
    queue.push({
      type: e.originalType,
      options: e.options,
      data: e.detail,
    });
  });

  jail.style.display = 'none';
  jail.referrer = 'no-referrer';
  jail.id = 'jail';
  jail.name = window.name;
  jail.src = '/gtm?id=' + global.CONTAINER_ID;
  jail.onload = function() {
    preload.off();

    for (var i = 0; i < queue.length; i++) {
      var queuedEvent = queue[i];
      r.frames.postMessage(
        jail.contentWindow,
        queuedEvent.type,
        queuedEvent.data,
        queuedEvent.options
      );
    }
  };

  document.body.appendChild(jail);

  r.frames.proxy('gtm', [jail.contentWindow, window.parent]);
})(this, this.r);
