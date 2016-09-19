/* The ready method */
$(function() {
  if (!r.config.link_websocket_url) {
    return;
  }

  var removedEmptyMessage = !$('#noresults').length;
  var msToDisplayNewComments = 30 * 1000;

  // Areas to insert new comments
  var $liveCommentsArea = $('#live-comments');
  var $siteTable = $('.sitetable.nestedlisting');

  var commentsToInsert = [];
  var parentsOfCommentsToInsert = {};

  // Count of total comments
  var totalCommentsVisible = $siteTable.find('.thing.comment').length;
  var maxCommentsToHold = r.config.link_limit + 20;

  // Update number of new comments pending
  var $newCommentsCountElement = $('.new-comments-waiting');

  // Update total number of comments
  var $flatListCommentsButton = $('.link:first').find('.flat-list.buttons').find('.comments');
  var $commentAreaTitle = $('.commentarea').find('.panestack-title').find('.title');
  var totalCommentsCount = 0;

  // Maintain timer for comment insertion batching
  var lastCommentInsert = 0;
  var msToWait = 1000;
  var timer = null;
  var lastButtonClick = null;


  var websocketEvents = {
    'message:new_comment': function(message) {
      // If current user is the author, the comment has already
      // been added to the DOM after POST_comment was called
      if (message.author_id == r.config.user_id) {
        return;
      }

      // Show mod version or user version?
      if (r.config.is_posts_mod) {
        var commentHtml = message.mod_comment_html;
      } else {
        var commentHtml = message.comment_html;
      }

      if (!message.parent_fullname) {
        // Top level comment
        var elementInViewId = $siteTable.attr('id');
      } else {
        // Child comment
        var elementInViewId = '#thing_' + message.parent_fullname;
        if (!$(elementInViewId).length) {
          // The parent hasn't been added to the page,
          // so don't add this child
          return;
        }
      }

      // Trim whitespace between element nodes to prevent text nodes
      commentHtml[0].data.content = commentHtml[0].data.content.trim().replace(/>\s+</g, "><");
      // Prevent XSS vulnerability by escaping html content
      commentHtml[0].data.content = _.escape(commentHtml[0].data.content);

      parentsOfCommentsToInsert[elementInViewId] = true;
      commentsToInsert.push(commentHtml[0]);
      // Slice of the last n comments if the limit is too big (in batches)
      if (commentsToInsert.length > r.config.link_limit + maxCommentsToHold) {
        commentsToInsert = commentsToInsert.slice(-r.config.link_limit);
      }

      // Update the number of total comments
      if (message.total_comment_count) {
        totalCommentsCount = message.total_comment_count;
      }

      if (!removedEmptyMessage) {
        $('#noresults').remove();
        removedEmptyMessage = true;
      }

      var now = new Date().getTime();
      if (timer === null) {
        // If a comment has been inserted within the last interval
        // period, batch the comments
        if (lastCommentInsert + msToWait < now) {
          timer = setTimeout(insertBatchedComments, msToWait);
        } else {
          // If it's been a while since a comment, insert immediately
          insertBatchedComments();
        }
      }
    }
  };

  function insertBatchedComments(force) {
    lastCommentInsert = new Date().getTime();
    timer = null;

    if (!Object.keys(parentsOfCommentsToInsert).length || !commentsToInsert.length) {
      return;
    }

    shouldDisplay = shouldDisplayComments(parentsOfCommentsToInsert);
    // New comments should be visible
    if (shouldDisplay || force) {
      var elementList = $.insert_things(commentsToInsert.slice(-r.config.link_limit), false, true, $siteTable);
      totalCommentsVisible += elementList.length;
      if (commentsToInsert.length - elementList.length > 0) {
        commentsToInsert = commentsToInsert.slice(-(commentsToInsert.length - elementList.length));
      } else {
        commentsToInsert = []
      }
      parentsOfCommentsToInsert = {};
      showNewComments(elementList);
      // If there are more comments visible than desired for this page and
      // comments are visible, remove a comment
      if (r.config.link_limit && totalCommentsVisible + 1 > r.config.link_limit) {
        removeLastComments();
      }
    } else if (lastButtonClick + msToWait < lastCommentInsert) {
      // New comments are hidden so update the 'new comments' counter
      // Don't show this button if it's been clicked in the past second
      $liveCommentsArea.css('max-height', '50px');
      if (commentsToInsert.length === 1) {
        $newCommentsCountElement.text(r._('Show 1 new comment'));
      } else {
        $newCommentsCountElement.text(r._('Show %(count)s new comments').format({count: commentsToInsert.length}));
      }
    }

    // Update the number of total comments in the flatlist and comment area title
    if (totalCommentsCount === 1) {
      var flatListCommentsButtonText = r._('%(count)s comment').format({count: totalCommentsCount});
    } else {
      var flatListCommentsButtonText = r._('%(count)s comments').format({count: totalCommentsCount});
    }
    var commentAreaTitleText = r._('all %(count)s comments').format({count: totalCommentsCount});
    $flatListCommentsButton.text(flatListCommentsButtonText);
    $commentAreaTitle.text(commentAreaTitleText);
  }

  $('.new-comments-waiting').click(function() {
    // Click on the new comments modal to show the hidden comments
    lastButtonClick = new Date().getTime();
    $liveCommentsArea.css('max-height', '0px');

    // Scroll to the top of the site table
    $('html, body').animate({scrollTop: $commentAreaTitle.offset().top}, 'normal');

    // Insert the buffered comments
    insertBatchedComments(true);
  });

  function showNewComments(elementList) {
    // Fade the new comments in and apply the new comment style
    // to the tagline for a little bit of time
    var taglines = [];
    for (var i=0; i < elementList.length; i++) {
      var $element = $(elementList[i]);
      var $tagline = $element.find('.tagline:first');
      $tagline.addClass('new-live-comment');
      taglines.push($tagline);
      $element.fadeIn(200);
    }

    setTimeout(function() {
      for (i=0; i<taglines.length; i++) {
        taglines[i].removeClass('new-live-comment');
      }
    }, msToDisplayNewComments);
  };

  function shouldDisplayComments(parentElements) {
    // Conditions to make the comments visible:
    // all top level comments, sitetable needs to be in view or below
    // all children comments, all parents need to be in view or below
    // mixture of children and top level comments, sitetable needs to be in view or below
    if (!Object.keys(parentElements).length) {
      return false;
    }

    // the "new comments" button is visible, so live comments are paused
    if (!($liveCommentsArea.css('max-height') === '0px')) {
      return false;
    }

    // if a comment is being added to the $siteTable, then at
    // minimum the $siteTable should be in the viewport (or below)
    if ($siteTable.attr('id') in parentElements) {
      return isOnScreenOrBelow($siteTable, true);
    }

    // if a comment is being added to parents, search all of them
    // until one fails
    Object.keys(parentElements).forEach(function(key) {
      if (!isOnScreenOrBelow($(key), true)) {
        return false;
      }
    });
    return true;
  }

  function isOnScreenOrBelow(el, showElementsBelow) {
    // Calculates whether the element is on the window view vertically
    var viewport = {};
    viewport.top = $(window).scrollTop();
    viewport.bottom = viewport.top + $(window).height();

    var bounds = {};
    bounds.top = el.offset().top;
    bounds.bottom = bounds.top + el.outerHeight();

    if ((bounds.top <= viewport.bottom) && (bounds.top >= viewport.top)) {
      return true;
    } else if (showElementsBelow && bounds.top > viewport.bottom) {
      return true;
    } else {
      return false;
    }
  };

  function removeLastComments() {
    // Remove the last comments so that the page doesn't overflow
    // with comments and stays within the specified link_limit
    var comments = $siteTable.find('.thing.comment');
    if (comments.length - r.config.link_limit <= 0) {
      return;
    }
    comments.slice(r.config.link_limit-comments.length).remove();
    $siteTable.find('.clearleft').slice(r.config.link_limit-comments.length).remove();
  }

  var websocket = new r.WebSocket(r.config.link_websocket_url);
  websocket.on(websocketEvents);
  websocket.start();
});
