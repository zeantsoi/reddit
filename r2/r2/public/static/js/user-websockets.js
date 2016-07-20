/* The ready method */
$(function() {
  if (!r.config.user_websocket_url) {
    return;
  }
  var userKey = r.config.user_id + '-websocket';
  var orangeredKey = r.config.user_id + '-orangered';
  var orangeredTimestampKey = r.config.user_id + '-orangered-ts';
  var websocketUrl = r.config.user_websocket_url;
  var millisecondsToBatch = 30000;

  // New message or comment reply:
  // Flash toast, update inbox count, and update
  // inbox orangered CSS
  function flashNewMessage(message) {
    var messageText = "You have a new %(messageType)s!".format(
      {messageType: message.msg_type});

    $('.new-message').html('<a href="%(permalink)s">%(messageText)s</a>'.format(
        {permalink: message.permalink, messageText: messageText}));
    $('.new-message').fadeIn(1000).delay(5000).fadeOut(1000);

    if ($('.message-count').length) {
      // Already havemail state so just increment count
      $('.message-count').html(message.inbox_count);
    } else {
      // Set the have mail state and add the inbox count
      $('#mail').removeClass('nohavemail');
      $('#mail').addClass('havemail');
      $('#mail').attr("href", "/message/unread/");
      $('#mail').attr("title", "new mail!");
      $('<a class="message-count" href="/message/unread/">'
        + message.inbox_count + '</a>').insertAfter('#mail');
    }
  }

  function updateMessageCount(inboxCount) {
    if ($('.message-count').length) {
      // Already havemail state so just increment count
      $('.message-count').html(inboxCount);
    } else {
      // Set the havemail state and add the inbox count
      $('#mail').removeClass('nohavemail');
      $('#mail').addClass('havemail');
      $('#mail').attr("href", "/message/unread/");
      $('#mail').attr("title", "new mail!");
      var $messageCount = $('<a class="message-count" href="/message/unread/"></a>');
      $messageCount.text(inboxCount);
      $messageCount.insertAfter('#mail');
    }
  }

  // localStorage events that should be processed
  var websocketStorageEvents = function (event) {
    // New orangered has been received
    if (event.key === orangeredKey) {
      var message = JSON.parse(event.newValue);
      if (!message) {
        return;
      }
      updateMessageCount(message[message.length-1].inbox_count);
    }
  };

  // Broadcast messages expected to be received
  var websocketEvents = {
    'message:new_orangered': function(message) {
      var jsonItems = [];
      var storageItems = store.safeGet(orangeredKey);
      // Append the newest message to the end of the storage array
      // (convert to Array if not already)
      try {
        if (storageItems) {
          storageItems = storageItems;
          if (Array.isArray(storageItems)) {
            jsonItems = storageItems;
          }
        }
      } catch (e) {
        // Invalid json items - remove them
        store.remove(orangeredKey);
      }
      jsonItems.push(message);
      store.safeSet(orangeredKey, jsonItems);
      updateMessageCount(message.inbox_count);
      sendBatchedNotifications();
    }
  };

  function sendBatchedNotifications() {
    var now = new Date();
    var date = store.safeGet(orangeredTimestampKey) || '';
    // If the last message was less than millisecondsToBatch ago,
    // wait millisecondsToBatch to batch more potential messages
    if (!date || now - new Date(date) >= millisecondsToBatch) {
      flashNewMessage();
    }
  }

  var websocket = new r.WebSocket(websocketUrl);
  websocket.startPerBrowser(
    userKey,
    websocketUrl,
    websocketEvents,
    websocketStorageEvents
  );

});
