function toggleNotificationsStatus() {
  if ($('#live_orangereds').prop('checked')) {
    $('.browser-notifications').show();
  } else {
    $('.browser-notifications').hide();
  }
}

function updateStatus() {
  var requestStatus = $('#status');
  var className = 'info-icon';
  if (!window.Notification) {
    var status_text = r._("Sorry! Browser notifications aren't yet supported in this browser");
  } else if (Notification.permission === "granted") {
    className = 'success-icon';
    if (!r.config.user_websocket_url) {
      var status_text = r._("Success! When this feature is released, you'll be all set!");
    } else {
      var status_text = r._("Success! You're done.");
    }
    $('#test-notifications').show();
  } else if (Notification.permission === "denied") {
    var status_text = '';
    className = 'error-icon';

    var userAgent = navigator.userAgent.toLowerCase();
    if (/firefox/.test(userAgent)) {
      status_text = r._('Green lock next to the URL > change Receive Notifications to "allow"');
    } else if (/chrome/.test(userAgent)) {
      status_text = r._('Green lock next to the URL > change Notifications to "always allow on this site"');
    } else {
      status_text = r._("To finish, change your browser's Notification settings for reddit.com");
    }
  } else {
    var status_text = r._('Click "Allow" for browser notifications to be shown for reddit.com');
    var requestPermsButton = $('#request-permissions');
    requestPermsButton.html(r._('(try again)'));
    requestPermsButton.show();
  }
  requestStatus.addClass(className);
  requestStatus.html(status_text);
}

function requestPerms() {
  if (!window.Notification) {
    return false;
  }

  Notification.requestPermission().then(function(result) {
    payload = {"permission": result,
      "tab_in_focus": !document.hidden,
      "pref_email_messages": r.config.pref_email_messages};
    r.analytics.sendEvent("browser_notification_events", "request_permission", null, payload);

    if (result !== 'default') {
      $('#status').removeClass('info-icon');
      updateStatus();
      // hide request permissions (try again) button
      $('#request-permissions').html('');
      $('#request-permissions').hide();
    }
  });
}

function testNotification() {
  var messageNotification = new Notification(r._("Look at this fancy notification!"),
    {
      icon: r.utils.staticURL('circled-snoo-2x.png'),
      body: r._('We did it Reddit!'),
  });

  messageNotification.onclick = function(event) {
    event.preventDefault();
    //Yeah you know where this leads
    window.open('https://www.youtube.com/watch?v=dQw4w9WgXcQ', '_blank');
  };

  setTimeout(function() {
    messageNotification.close();
  }, 3000);
}

/* The ready method */
$(function() {
  updateStatus();

  // Request permissions on page load only if the pref is checked
  if ($('#live_orangereds').prop('checked')) {
    requestPerms();
  } else {
    // If the pref isn't checked, hide notification status
    toggleNotificationsStatus();
  }

  // When the pref is toggled, adjust the notification status visibility
  $('#live_orangereds').click(function(e) {
    toggleNotificationsStatus();
  });

  $('#request-permissions').click(function(e) {
    requestPerms();
    return false;
  });

  $('#test-notifications').click(function(e) {
    testNotification();
    return false;
  });
});
