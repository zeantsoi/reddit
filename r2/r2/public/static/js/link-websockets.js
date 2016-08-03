/* The ready method */
$(function() {
  if (!r.config.link_websocket_url) {
    return;
  }

  var msToDisplayNewComments = 30 * 1000;

  var websocketEvents = {
    'message:new_comment': function(message) {
      // If current user is the author, the comment has already
      // been added to the DOM after POST_comment was called
      if (message.author_id == r.config.user_id) {
        return;
      }

      // Comment has already been inserted
      if ($('#thing_' + message.comment_fullname).length) {
        return;
      }

      $('#noresults').remove();
      // Append the comment to bottom of page if sort != new
      var append = r.config.link_sort !== 'new';
      var $liveCommentsArea = $('#live-comments');

      // Show mod version or user version?
      if (r.config.is_posts_mod) {
        var comment_html = message.mod_comment_html;
      } else {
        var comment_html = message.comment_html;
      }

      if (!message.parent_fullname) {
        // Top level comment
        var $elementInView = $liveCommentsArea;
      } else {
        // Child comment
        var $elementInView = $('#thing_' + message.parent_fullname);
        if (!$elementInView.length) {
          // The parent hasn't been added to the page,
          // so add the comment to the default area
          $elementInView = $liveCommentsArea;
        }
      }

      var commentsVisible = $liveCommentsArea.css('max-height') === '0px';
      if (isOnScreenOrBelow($elementInView, !append) && commentsVisible) {
        // The element to insert the comment in is in view
        // so add the comment and show it
        var elementList = $.insert_things(comment_html, append, true);
        showNewComments(elementList);
      } else {
        // Insert the elements as hidden and display the area
        // for users to click to display comments
        $.insert_things(comment_html, append, true);
        if (commentsVisible) {
          $liveCommentsArea.css('max-height', '50px');
        }
      }
      $('#noresults').remove();
    }
  };

  $('.new-comments-waiting').click(function() {
    // Click on the new comments modal to show the hidden comments
    var elementList = $('div.thing:hidden');
    $('#live-comments').css('max-height', '0px');
    showNewComments(elementList);
  })

  function showNewComments(elementList) {
    // Fade the new comments in and apply the new comment style
    // to the tagline for a little bit of time
    for (var i=0; i < elementList.length; i++) {
      var $element = $(elementList[i]);
      var $tagline = $element.find('.tagline:first');
      $tagline.addClass('new-live-comment');
      setTimeout(function() {
        $tagline.removeClass('new-live-comment');
      }, msToDisplayNewComments);

      $element.fadeIn(300);
    }
  };

  function isOnScreenOrBelow(el, showElementsBelow) {
    // Calculates whether the element is on the window view vertically
    var viewport = {};
    viewport.top = $(window).scrollTop();
    viewport.bottom = viewport.top + $(window).height();

    var bounds = {};
    bounds.top = el.offset().top;
    bounds.bottom = bounds.top + el.outerHeight();

    if ((bounds.top <= viewport.bottom) && (bounds.bottom >= viewport.top)) {
      return true;
    } else if (showElementsBelow && bounds.top > viewport.bottom) {
      return true;
    } else {
      return false;
    }
  };


  var websocket = new r.WebSocket(r.config.link_websocket_url);
  websocket.on(websocketEvents);
  websocket.start();
});
