(function($) {
  $.fn.superban = function (kind, nostore) {
      if(!$.defined(nostore) || !nostore) {
          $(this).store_state('ban', kind, "author");
      }
      $(this).same_author().each(function() { 
          $(this)
            .removeClass("ban")
            .removeClass("x-ban")
            .removeClass("ninjaban")
            .addClass(kind)
            .find(".superman-box").hide();
      });
      return false; 
  };
  $.fn.findshills = function (stage) {
    var thing = $(this);
    if (stage == 0) {
      thing.children('.entry').find('.find-shills.saving').show();
      setTimeout(function() { thing.findshills(1); }, 1500 );
    } else {
      thing.children('.entry').find('.find-shills.saving').hide();
      thing.children('.entry').find('.find-shills.jobid').show();
    }
  };
  $.fn.refudge = function () {
    var thing = $(this);
    var base_score = parseInt(thing.attr("base_score"));
    var fudge = parseInt(thing.attr("votefudge"));
    var fake_score = base_score + fudge;
    if (isNaN(fake_score)) {
      return;
    }
    var score_likes = fake_score + 1;
    var score_unvoted = fake_score;
    var score_dislikes = fake_score - 1;

    if (fudge >= 10) {
      score_likes = superman_inf();
    }

    if (fudge <= -10) {
      score_dislikes = "-" + superman_inf();
    }

    if (thing.hasClass("comment") || thing.hasClass("compressed")) {
      score_likes += Math.abs(score_likes) == 1 ? " point" : " points";
      score_unvoted += Math.abs(score_unvoted) == 1 ? " point" : " points";
      score_dislikes += Math.abs(score_dislikes) == 1 ? " point" : " points";
    }

    thing.children(".entry, .midcol").find(".score.likes").html(score_likes);
    thing.children(".entry, .midcol").find(".score.unvoted").html(score_unvoted);
    thing.children(".entry, .midcol").find(".score.dislikes").html(score_dislikes);
  }
  $.fn.realvote = $.fn.vote;
  $.fn.vote = function(vh, callback, event) {
    var elem = $(this);

    if ( ! is_superman() ) {
      return elem.realvote(vh, callback, event);
    }

    var thing = elem.thing();
    var up = elem.hasClass("upmod") || elem.hasClass("up");
    var mod = elem.hasClass("upmod") || elem.hasClass("downmod");
    var fudge = parseInt(thing.attr("votefudge"));
    if (isNaN(fudge)) {
      fudge = 0;
    }
    if (mod) {
      if (up) {
        if (++fudge > 10) {
          fudge = 10;
        }
      } else {
        if (--fudge < -10) {
          fudge = -10;
        }
      }
      thing.store_state('fudge', fudge);
      thing.attr("votefudge", fudge);
      thing.refudge();
    } else {
      elem.realvote(vh, callback, event);
    }
  };

  var state_cookie = "state";
  $.fn.store_state = function(action, data, thing_id_sel) {
      thing_id_sel = $.with_default(thing_id_sel, "thing");
      $.cookie_name_prefix('');
      var c = $.cookie_read(state_cookie).data || [];
      if (reddit.logged) {
          $.cookie_name_prefix(reddit.logged);
      }
      var tid = $(this).thing_id(thing_id_sel);
      var found = false;
      for (var i = 0; i < c.length; i++) {
          if (c[i][0] == tid && c[i][1] == action) {
              found = true;
              c[i][2] = data;
          }
      }
      if(!found) {
          c.push([tid, action, data]);
      }
      // Loop over c, getting rid of things off the beginning
      // until it fits in 4000 bytes. But just in case there's
      // some sort of weird bug I'm not seeing, give up after
      // 100 times so there's no chance of an endless loop.
      var i;
      for (i = 0; i < 100; i++) {
        var len = $.toJSON(c).length;
        if (len > 4000) {
          c.shift();
        }
      }
      $.cookie_name_prefix("");
      $.cookie_write({name: state_cookie, data: c});
      if (reddit.logged) {
          $.cookie_name_prefix(reddit.logged);
      }
  };

  $.read_state = function() {
      $.cookie_name_prefix("");
      var c = $.cookie_read(state_cookie);
      if (reddit.logged) {
          $.cookie_name_prefix(reddit.logged);
      }
      if (c) {
          c = c.data;
          for (var i = 0; i < c.length; i++) {
              var things = $.things(c[i][0]);
              if (things.length == 0) {
                  things = $(".author.id-" + c[i][0]).parents(".thing:first");
              }
              things.each(function() {
                  var thing = $(this);
                  var action = c[i][1];
                  var data = c[i][2];
                  if (action == 'title') {
                      thing.find("a.title").html(data);
                  } else if (action == 'fudge') {
                      thing.attr("votefudge", parseInt(data));
                      thing.refudge();
                  } else if (action == 'ban') {
                      thing.superban(data, true);
                  }
              });
          }
      }
  };

})(jQuery);

$(function() {
///    var first_time = $.cookie_read("superfirst").data;
///    if (first_time == '') {
///      $("body > .content").prepend("<div class='infobar '><div class='md'><p>reddit is a source for what's new and popular online. vote on vote o<span style='font-family:monospace; color: red;'>ERROR! initvars() app_globals.py:422<br/>couldn't load $CONFIG{{admins}} Defaulting to &lt;*&gt;</span></p></div></div>");
///      $.cookie_write({name: "superfirst", data: 1});
///    }

    $.read_state();
  });
