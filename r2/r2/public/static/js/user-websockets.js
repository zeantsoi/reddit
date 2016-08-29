/* The ready method */
$(function() {
  if (!r.config.user_websocket_url) {
    return;
  }
  var userKey = r.config.user_id + '-websocket';
  var orangeredKey = r.config.user_id + '-orangered';
  var orangeredTimestampKey = r.config.user_id + '-orangered-ts';
  var inboxCountKey = r.config.user_id + '-inboxcount';
  var websocketUrl = r.config.user_websocket_url;
  var millisecondsToBatch = 30000;
  var messageNotificationMilliseconds = 7000;

  // New message or comment reply -- send browser notification
  function flashNewMessage(messageBody) {
    var inboxMessages = store.safeGet(orangeredKey);
    var messageType;
    var messageText;
    // The messages have already been processed
    if (inboxMessages === null) {
      return;
    }

    // Get minimum of the count of recent batches or the inbox count
    // (since some messages can be read during the batching period)
    var recentNewMessageCount = Math.min(inboxMessages.length, inboxMessages[inboxMessages.length-1].inbox_count);

    // Get number of unread messages to tell if plural or not
    if (recentNewMessageCount === 1) {
      messageType = inboxMessages[0].msg_type;
      messageText = messageBody;
    } else {
      messageType = 'messages';
      messageText = r._("You have %(count)s new messages!").format({count: recentNewMessageCount});
    }

    if (r.config.live_orangereds_pref && !!Notification && Notification.permission !== "granted") {
      Notification.requestPermission().then(function(result) {
        payload = {"permission": result,
          "tab_in_focus": !document.hidden,
          "pref_email_messages": r.config.pref_email_messages};
        r.analytics.sendEvent("browser_notification_events", "request_permission", null, payload);

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
      payload = {"new_messages": recentNewMessageCount,
        "tab_in_focus": !document.hidden,
        "pref_email_messages": r.config.pref_email_messages};
      r.analytics.sendEvent("browser_notification_events", "new_orangered", null, payload);

      messageNotification.onclick = function(event) {
        var payload = {"inbox_count": inboxMessages[inboxMessages.length-1].inbox_count,
          "tab_in_focus": !document.hidden,
          "pref_email_messages": r.config.pref_email_messages};
        r.analytics.sendEvent("browser_notification_events", "orangereds_click", null, payload);
        event.preventDefault();
        window.open('/message/unread/', '_blank');
      };
      setTimeout(function(){
        messageNotification.close();
      }, messageNotificationMilliseconds);
  }

  function updateMessageCount(inboxCount) {
    if (inboxCount < 1) {
      // No unread messages
      $('.message-count').remove();
      $('#mail').addClass('nohavemail');
      $('#mail').removeClass('havemail');
      $('#mail').attr('href', '');
      $('#mail').attr('title', '');
    } else {
      if ($('.message-count').length) {
        // Already havemail state so just increment count
        $('.message-count').text(inboxCount);
      } else {
        // Set the havemail state and add the inbox count
        $('#mail').removeClass('nohavemail');
        $('#mail').addClass('havemail');
        $('#mail').attr('href', '/message/unread/');
        $('#mail').attr('title', 'new mail!');
        var $messageCount = $('<a class="message-count" href="/message/unread/"></a>');
        $messageCount.text(inboxCount);
        $messageCount.insertAfter('#mail');
      }
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
    } else if (event.key === inboxCountKey) {
      updateMessageCount(event.newValue);
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
      sendBatchedNotifications(message.msg_body);
    },
    'message:messages_read': function(message) {
      var storageItems = store.safeGet(inboxCountKey);
      store.safeSet(inboxCountKey, message.inbox_count);
      updateMessageCount(message.inbox_count);
    }
  };

  function sendBatchedNotifications(messageBody) {
    var now = new Date();
    var date = store.safeGet(orangeredTimestampKey) || '';
    // If the last message was less than millisecondsToBatch ago,
    // wait millisecondsToBatch to batch more potential messages
    if (!date || now - new Date(date) >= millisecondsToBatch) {
      flashNewMessage(messageBody);
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
