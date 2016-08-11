!function(r) {
  function isPluginExpandoButton(elem) {
    // temporary fix for RES http://redd.it/392zol
    return elem.tagName === 'A';
  }

  /*
  This is a temporary hack to block RES from hijacking our expando _only_ on
  when it is auto-expanded.  The current behavior without this hack will cause
  a double-expando (ours being visible initially, and a second when the RES user
  tries to collapse it).  We want to prevent RES users from having a poor
  experience with release of the new media preview features, so we're hacking in
  a fix on _our_ end and giving RES a hard deadline to fix it on theirs.

  RES removes our expando button completely and seems to be swallowing click
  events on theirs.  This fixes it by using a MutationObserver, which any
  RES-supported browser should support.  We'll watch for RES's button swap, and
  simply swap it back in with our own.

  https://developer.mozilla.org/en-US/docs/Web/API/MutationObserver
   */
  function blockPluginExpando(view) {
    try {
        var entryNode = view.$el.find('.entry')[0];
        var originalButton = view.$button[0];
        var pluginButton;
        var removedButton;

        var observer = new MutationObserver(function(mutations) {
          mutations.forEach(function(mutationRecord) {
            // look for mutations adding a new expando-button element
            if (mutationRecord.addedNodes.length &&
                $(mutationRecord.addedNodes[0]).is('.expando-button')) {
              pluginButton = mutationRecord.addedNodes[0];
            }

            // look for mutations removing the original expando-button element
            if (mutationRecord.removedNodes.length &&
                mutationRecord.removedNodes[0] === originalButton) {
              removedButton = originalButton;
            }

            // when both mutations have been observed, stop observing and undo
            if (pluginButton && removedButton) {
              observer.disconnect();
              $(pluginButton).before(removedButton).remove();
            }
          });
        });

        observer.observe(entryNode, { childList: true });

        // if nothing happens for 5 seconds, probably safe to say they don't have RES
        setTimeout(function() {
          observer.disconnect();
        }, 5000);
      } catch (err) {
      }
  }

  function includeElementClicks(target) {
    var $target = $(target);

    // Don't expand on any of the flat-list buttons
    if ($target.parentsUntil('.thing', '.flat-list').length) {
      return false;
    }
    // Don't expand on the author or subreddit links in tagline
    if ($target.hasClass('author') || $target.hasClass('subreddit')) {
      return false;
    }
    // Don't expand on domain click
    if ($target.parentsUntil('.thing', '.domain').length) {
      return false;
    }
    // Don't expand on share form modal
    if ($target.parentsUntil('.thing', '.post-sharing').length) {
      return false;
    }
    // Don't expand on report form modal
    if ($target.parentsUntil('.thing', '.reportform').length) {
      return false;
    }
    // Don't expand on selfpost body clicks
    if ($target.parentsUntil('.thing', '.md').length) {
      return false;
    }
    // Clicking on the expando should open the link,
    // but not hide it
    if ($target.parentsUntil('.thing', '.media-preview').length) {
      return false;
    }

    // Don't expand on title click unless the experiment variant
    // "clickbox_with_title" is enabled
    if (!r.config.feature_clickbox_with_title && $target.hasClass('title') && $target.hasClass('may-blank')) {
      return false;
    }

    return true;
  }
  var Expando = Backbone.View.extend({
    buttonSelector: '.expando-button',
    expandoSelector: '.expando',
    expanded: false,

    events: {
      'click .expando-button': 'toggleExpando',
      'click .expand-media.preview-object': 'toggleExpandoFromLink'
    },

    constructor: function() {
      Backbone.View.prototype.constructor.apply(this, _.toArray(arguments));

      this.afterInitialize();
    },

    initialize: function() {
      this.$button = this.$el.find(this.buttonSelector);
      this.$expando = this.$el.find(this.expandoSelector);
    },

    afterInitialize: function() {
      this.expand();
    },

    toggleExpando: function(e) {
      if (isPluginExpandoButton(e.target)) { return; }

      this.expanded ? this.collapse() : this.expand();
    },

    toggleExpandoFromLink: function(e) {
      var expandoButton = $('.expando-button').next();
      if (isPluginExpandoButton(expandoButton)) { return; }
      // Prevent expando-button and thumbnail clicks (in same div)
      // from triggering the expand/collapse twice
      if ($(e.target).hasClass('expando-button')) { return; }
      if ($(e.currentTarget).hasClass('thumbnail')) { return; }
      if (!includeElementClicks(e.target)) { return; }

      this.expanded ? this.collapse() : this.expand();
    },

    expand: function() {
      this.$button.addClass('expanded')
                  .removeClass('collapsed');
      this.expanded = true;
      this.show();
    },

    show: function() {
      this.$expando.show();
    },

    collapse: function() {
      this.$button.addClass('collapsed')
                  .removeClass('expanded');
      this.expanded = false;
      this.hide();
    },

    hide: function() {
      this.$expando.hide();
    }
  });

  var LinkExpando = Expando.extend({
    events: _.extend({}, Expando.prototype.events, {
      'click .open-expando': 'expand',
    }),

    initialize: function() {
      Expando.prototype.initialize.call(this);

      this.cachedHTML = this.$expando.data('cachedhtml');
      this.loaded = !!this.cachedHTML;
      this.id = this.$el.thing_id();
      this.isNSFW = this.$el.hasClass('over18');
      this.linkType = $.getThingType(this.$el);
      this.autoexpanded = this.options.autoexpanded;

      if (this.autoexpanded) {
        blockPluginExpando(this);

        this.loaded = true;
        this.cachedHTML = this.$expando.html();
      }

      var $e = $.Event('expando:create', { expando: this });
      $(document.body).trigger($e);

      if ($e.isDefaultPrevented()) { return; }

      $(document).on('hide_thing_' + this.id, function() {
        this.collapse();
      }.bind(this));

      var linkURL = $.getLinkURL(this.$el);

      // event context
      var eventData = {
        linkIsNSFW: this.isNSFW,
        linkType: this.linkType,
        linkURL: linkURL,
      };
      
      // note that hyphenated data attributes will be converted to camelCase
      var thingData = this.$el.data();

      if ('fullname' in thingData) {
        eventData.linkFullname = thingData.fullname;
      }

      if ('timestamp' in thingData) {
        eventData.linkCreated = thingData.timestamp;
      }

      if ('domain' in thingData) {
        eventData.linkDomain = thingData.domain;
      }

      if ('authorFullname' in thingData) {
        eventData.authorFullname = thingData.authorFullname;
      }

      if ('subreddit' in thingData) {
        eventData.subredditName = thingData.subreddit;
      }

      if ('subredditFullname' in thingData) {
        eventData.subredditFullname = thingData.subredditFullname;
      }

      this._expandoEventData = eventData;
    },

    collapse: function() {
      LinkExpando.__super__.collapse.call(this);
      this.autoexpanded = false;
    },

    show: function() {
      if (!this.loaded) {
        return $.request('expando', { link_id: this.id }, function(res) {
          var expandoHTML = $.unsafe(res);
          this.cachedHTML = expandoHTML;
          this.loaded = true;
          this.show();
        }.bind(this), false, 'html', true);
      }

      var $e = $.Event('expando:show', { expando: this });
      this.$el.trigger($e);

      if ($e.isDefaultPrevented()) { return; }

      if (!this.autoexpanded) {
        this.$expando.html(this.cachedHTML);
      }

      if (!this._expandoEventData.provider) {
        // this needs to be deferred until the actual embed markup is available.
        var $media = this.$expando.children();

        if ($media.is('iframe')) {
          this._expandoEventData.provider = 'embedly';
        } else {
          this._expandoEventData.provider = 'reddit';
        }
      }

      this.showExpandoContent();
      this.fireExpandEvent();
      r.analytics.fireRetargetingPixel(this.$el);
    },

    showExpandoContent: function() {
      this.$expando.removeClass('expando-uninitialized');
      this.$expando.show();
    },

    fireExpandEvent: function() {
      if (this.autoexpanded) {
        this.autoexpanded = false;
        r.analytics.expandoEvent('expand_default', this._expandoEventData);
      } else {
        r.analytics.expandoEvent('expand_user', this._expandoEventData);
      }
    },

    hide: function() {
      var $e = $.Event('expando:hide', { expando: this });
      this.$el.trigger($e);

      if ($e.isDefaultPrevented()) { return; }

      this.hideExpandoContent();
      this.fireCollapseEvent();
    },

    hideExpandoContent: function() {
      this.$expando.hide().empty();
    },

    fireCollapseEvent: function() {
      r.analytics.expandoEvent('collapse_user', this._expandoEventData);
    },
  });

  var SearchResultLinkExpando = Expando.extend({
    buttonSelector: '.search-expando-button',
    expandoSelector: '.search-expando',

    events: {
      'click .search-expando-button': 'toggleExpando',
    },

    afterInitialize: function() {
      var expandoHeight = this.$expando.innerHeight();
      var contentHeight = this.$expando.find('.search-result-body').innerHeight();

      if (contentHeight <= expandoHeight) {
        this.$button.remove();
        this.$expando.removeClass('collapsed');
        this.undelegateEvents();
      } else if (this.options.expanded) {
        this.expand();
      }
    },

    show: function() {
      this.$expando.removeClass('collapsed');
    },

    hide: function() {
      this.$expando.addClass('collapsed');
    },
  });

  $(function() {
    r.hooks.get('expando-pre-init').call();

    var listingSelectors = [
      '.linklisting',
      '.organic-listing',
      '.selfserve-subreddit-links',
    ];

    function initExpando($thing, autoexpanded) {
      if ($thing.data('expando')) {
        return;
      }

      $thing.data('expando', true);

      var view = new LinkExpando({
        el: $thing[0],
        autoexpanded: autoexpanded,
      });
    }

    function expandoOnClick(target, expandoButton){
      if (isPluginExpandoButton(expandoButton)) { return; }
      var $thing = $(target).closest('.thing');
      initExpando($thing, false);
    }

    $(listingSelectors.join(',')).on('click', '.expando-button', function(e) {
      expandoOnClick(this, e.target);
    });

    $(listingSelectors.join(',')).on('click', '.expand-media.source-redirect', function(e) {
      // If the clickbox target doesn't have a preview, imitate the behavior
      // of a title click
      if (!includeElementClicks(e.target)) { return; }
      var $mediaTarget = $(e.target).closest('.expand-media');
      var userPrefEnabled = r.config.new_window && (r.config.logged || !r.ui.isSmallScreen());
      var url = $mediaTarget.attr('data-href-url');
      if (userPrefEnabled) {
        var w = window.open(url, '_blank');
        // some popup blockers appear to return null for
        // `window.open` even inside click handlers.
        if (w !== null) {
            // try to nullify `window.opener` so the new tab can't
            // navigate us
            w.opener = null;
        }
      } else {
        location.href = url;
      }
    });

    $(listingSelectors.join(',')).on('click', '.expand-media.preview-object', function(e) {
      var expandoButton = $('.expando-button').next();
      if (!includeElementClicks(e.target)) { return; }
      expandoOnClick(this, expandoButton);
    });

    $('.link .expando-button.expanded').each(function() {
      var $thing = $(this).closest('.thing');
      initExpando($thing, true);
    });

    var searchResultLinkThings = $('.search-expando-button').closest('.search-result-link');

    searchResultLinkThings.each(function() {
      new SearchResultLinkExpando({ el: this });
    });
  });
}(r);
