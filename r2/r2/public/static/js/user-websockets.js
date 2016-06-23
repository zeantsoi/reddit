/* The ready method */
$(function() {
  if (!r.config.user_websocket_url) {
    return;
  }
  var userKey = r.config.user_id + '-websocket';
  var orangeredKey = r.config.user_id + '-orangered';
  var websocketUrl = r.config.user_websocket_url;

  // localStorage events that should be processed
  var websocketStorageEvents = function (event) {
    // New orangered has been received
    if (event.key === orangeredKey) {
      var message = JSON.parse(event.newValue);
    }
  };

  // Broadcast messages expected to be received
  var websocketEvents = {
    'message:new_orangered': function(message) {
      store.safeSet(orangeredKey, message);
    }
  };

  var websocket = new r.WebSocket(websocketUrl);
  websocket.startPerBrowser(
    userKey,
    websocketUrl,
    websocketEvents,
    websocketStorageEvents
  );

});
