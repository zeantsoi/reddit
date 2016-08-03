/* The ready method */
$(function() {
  if (!r.config.link_websocket_url) {
    return;
  }
  var websocketEvents = {
  };

  var websocket = new r.WebSocket(r.config.link_websocket_url);
  websocket.on(websocketEvents);
  websocket.start();
});
