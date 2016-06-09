;(function(gtm, global, r, undefined) {
  global.googleTagManager = global.googleTagManager || [];

  r.frames.listen('gtm');

  r.frames.receiveMessage('data.gtm', function(e) {
    global.googleTagManager.push(e.detail);
  });

  r.frames.receiveMessage('event.gtm', function(e) {
    global.googleTagManager.push(e.detail);
  });

  r.frames.postMessage(window.parent, 'loaded.gtm');

})((this.gtm = this.gtm || {}), this, this.r);
