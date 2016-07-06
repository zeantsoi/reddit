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
  var messageNotificationMilliseconds = 3000;

  // New message or comment reply -- send browser notification
  function flashNewMessage() {
    var inboxMessages = store.safeGet(orangeredKey);
    // The messages have already been processed
    if (inboxMessages === null) {
      return;
    }

    var recentNewMessageCount = inboxMessages.length;

    // Get number of unread messages to tell if plural or not
    if (recentNewMessageCount === 1) {
      var messageType = inboxMessages[0].msg_type;
      var messageText = "You have a new %(messageType)s!".format(
        {messageType: messageType});
    } else {
      var messageType = 'messages';
      var messageText = "You have %(count)s new messages!".format({count: recentNewMessageCount});
    }

    if (r.config.live_orangereds_pref && !!Notification && Notification.permission !== "granted") {
      Notification.requestPermission()

        if (result === "granted") {
          sendNotification(messageType, messageText, recentNewMessageCount, inboxMessages);
        }

      });
    } else if (r.config.live_orangereds_pref && !!Notification && Notification.permission === "granted") {
      sendNotification(messageType, messageText, recentNewMessageCount, inboxMessages);
    }

    // Remove all items from localstorage
    store.remove(orangeredKey);

    // Write timestamp to see if the next message needs to
    // wait millisecondsToBatch to batch more messages
    store.safeSet(orangeredTimestampKey, new Date());
  }

  function sendNotification(messageType, messageText, recentNewMessageCount, inboxMessages) {
    var messageNotification = new Notification("New %(messageType)s on Reddit".format(
        {messageType: messageType}), {
          icon: '/static/circled-snoo-2x.png',
          body: messageText,
      });

      messageNotification.onclick = function(event) {
        event.preventDefault();
        window.open('/message/unread/', '_blank');
      };
      setTimeout(function(){
        messageNotification.close();
      }, messageNotificationMilliseconds);
  }

  function updateMessageCount(inboxCount) {
    if ($('.message-count').length) {
      // Already havemail state so just increment count
      $('.message-count').text(inboxCount);
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
  var websocketStorageEvents = function(event) {
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
