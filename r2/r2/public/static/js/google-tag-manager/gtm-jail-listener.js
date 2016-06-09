;(function(global, r, undefined) {
  var jail = document.createElement('iframe');

  jail.style.display = 'none';
  jail.referrer = 'no-referrer';
  jail.id = 'jail';
  jail.name = window.name;
  jail.src = '/gtm?id=' + global.CONTAINER_ID +
    '&cb=' + global.CACHE_BUSTER;

  document.body.appendChild(jail);

  r.frames.proxy('gtm', [jail.contentWindow, window.parent]);
})(this, this.r);
