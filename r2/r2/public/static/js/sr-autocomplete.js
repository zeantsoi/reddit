/*
this file is a quick fix to help detangle frontend dependencies

Describes the r.srAutocomplete UI class that queries the database 
to search autocomplete subreddit queries.

consult subredditselector.html for config variables
*/
!function(r, _, $) {
  r.srAutocomplete = {
    NUM_SEED: 10, // number of subreddits to send as data for recommendations
    /* Mapping from keyname to keycode */
    KEYS: {
      BACKSPACE: 8,
      TAB: 9,
      ENTER: 13,
      ESCAPE: 27,
      LEFT: 37,
      UP: 38,
      RIGHT: 39,
      DOWN: 40,
    },
    SR_NAMES_DELIM: ',',
    selectedSr: {},
    origSr: '',
    MAX_SUBREDDITS: 100,
    MAX_DESCRIPTION_LENGTH: 200,
    hoverCardTemplate: _.template(
      '<div class="hovercard"> ' +
        '<h5> <%- title %> </h5>' +
        '<small> Description: <%- description %>\n</small>' +
        '<small> Subscribers: <%- subscribers %>\n</small>' +
      '</div>'
    ),
    _initialized: false,

    setup: function(srSearches, includeSearches, isMultiple, dynamicSuggestions) {
      this.srSearchCache = $.with_default(srSearches, {});
      this.srHovercardCache = {};
      this.includeSearches = includeSearches;
      this.isMultiple = isMultiple;
      this.dynamicSuggestions = dynamicSuggestions;
      this.suggestedSr = {};
      this.defaultSuggestedSr = {};
      this.oldSrName = '';
      var suggestions = $('#suggested-reddits')
                        .find('.sr-suggestion')
                        .map(function(index, val) {
                          return val.innerText;
                        });
      for(var i=0; i < suggestions.length; i++) {
        var suggestion = suggestions[i].toLowerCase();
        this.defaultSuggestedSr[suggestion] = true;
        this.suggestedSr[suggestion] = true;
      }

      this._bindEvents();

      this._initialized = true;
    },

    _bindEvents: function() {
      $('#sr-autocomplete-area').on('click', function() {
        $('#sr-autocomplete').focus();
      }.bind(this));

      if (this.includeSearches) {
        $('#sr-autocomplete').on('keyup', this.srNameUp.bind(this));
      }

      $('#sr-autocomplete')
        .on('keydown', this.srNameDown.bind(this))
        .on('blur', this.hideSrNameList.bind(this));

      $('.sr-name-row')
        .on('mouseover', this.highlightDropdown.bind(this))
        .on('mousedown', this.srDropdownMdown.bind(this))
        .on('mouseup', this.srDropdownMup.bind(this));

      $('#suggested-reddits').find('.sr-suggestion').each(function(index, elem) {
        var $suggestion = $(elem);
        $suggestion.on('click', this.setSrName.bind(this));
        if (this.isMultiple) {
          this._bindHovercard($suggestion);
        }
      }.bind(this));

      $('#add-all-suggestions-btn').on('click', this.srAddAllSuggestions.bind(this));

      $('#sr-autocomplete').on('sr-changed blur', function(e, data) {
        data = data || {};

        if (r.sponsored) {
          r.sponsored.render();
        }

        if (e.type !== 'sr-changed') {
          return;
        }

        var target = null;

        if (data.isAutocomplete) {
          target = 'autocomplete';
        } else if (data.isSuggestion) {
          target = 'suggestion';
        }

        // get new suggestions when new subreddits are added
        if (this.dynamicSuggestions &&
            !data.deleteSubreddit &&
            !data.noNewSuggestions) {
          this.srGetNewSuggestions(undefined, true);
        }

        // reset the suggestions to default when there are no selected subreddits
        if (this.dynamicSuggestions &&
          Object.keys(this.selectedSr).length === 0) {
          this.srSuggestionsReset();
        }

        if (r.sponsored && !data.deleteSubreddit) {
          r.analytics.adsInteractionEvent('select_subreddit', {
            srName: $.with_default(data.subreddit, ''),
            target: target,
          });
        }
      }.bind(this));
    },

    _bindHovercard: function($link) {
      return $link
        .on('mouseenter', this.srGetHovercard.bind(this))
        .on('mouseleave', this.srRemoveHovercard.bind(this));
    },

    /**
    @return the current selected subreddits
    */
    getSelectedSubreddits: function() {
      return Object.keys(this.selectedSr);
    },

    /*
    A dropdown row

    @param {String} name: name of the dropdown row
    @returns {jQuery} a jquery element to append to dropdown
    */
    srDropdownRow: function(name) {
      return $('<li />')
            .addClass('sr-name-row')
            .on('mouseover', this.highlightDropdown.bind(this))
            .on('mousedown', this.srDropdownMdown.bind(this))
            .on('mouseup', this.srDropdownMup.bind(this))
            .text(name);
    },

    /*
    @params {String} srName: text that goes inside
    @returns {jQuery} a jQuery span for a button
    */
    srToken: function(srName) {
      var removeButton = $('<img src="/static/kill.png"/>')
                        .on('click', this.srRemoveSr.bind(this));

      return $('<span />')
            .attr({class: 'sr-span'})
            .html(srName)
            .append(removeButton);
    },

    /**
    Creates a new subreddit suggestion

    @params {String}
    @returns {jQuery} element that represents a subreddit suggestion
    */
    srSuggestion: function(srName) {
      var $link = $('<a />')
                .attr({
                  href: '#',
                  class: 'sr-suggestion',
                  tabindex: '100',
                })
                .on('click', this.setSrName.bind(this))
                .text(srName);

      if (this.isMultiple) {
        this._bindHovercard($link);
      }
      return  $('<li />').append($link);
    },

    /**
    Creates a new hovercard

    @params {object} info JSON
    @returns {jQuery} element that represents a hovercard
    */
    srHovercard: function(info) {
      var description = info.public_description || 'none';
      if (description.length > this.MAX_DESCRIPTION_LENGTH) {
        description = description.substring(0, this.MAX_DESCRIPTION_LENGTH) + '...';
      }
      var subscribers = info.subscribers || 'unknown';
      var title = info.display_name;

      return this.hoverCardTemplate({
        title: title,
        description: description,
        subscribers: subscribers,
      });
    },

    /*
    Queries for subreddit name. Updates the dropdown (UI)

    Params:
    @params {String} query: text to search in database

    @returns: Nothing
    */
    srSearch: function(query) {
      query = query.toLowerCase();
      var cache = this.srSearchCache;
      if (!cache[query]) {
        $.request(
          'search_reddit_names.json', 
          {query: query, include_over_18: r.config.over_18},
          function (resp) {
            cache[query] = resp.names;
            r.srAutocomplete.srUpdateDropdown(resp.names);
          });
      } else {
        this.srUpdateDropdown(cache[query]);
      }

    },

    /**
    Validator for adding subreddits

    @params {function} successFn: callback for success (found subreddit)
    @params {Integer} retries: if ratelimited, retry again in 2 seconds

    @return {null}
    **/
    srIsValidSubreddit: function(query, successFn, retries) {
      $('.SUBREDDIT_NOEXIST').text('loading...').show();
      successFn = successFn.bind(this);
      if (!query) {
        return this.srShowNoSubredditExistsErrorMsg(query);
      }

      query = query.toLowerCase();
      $.request('search_reddit_names.json', 
        {
          query: query, 
          include_over_18: r.config.over_18,
          exact: true,
        },
        function (resp) {
          $('.field-sr').hide();
          if (resp.names.length == 1) {
            this.srHideErrorMsg();
            successFn(query);
          } else {
            this.srShowNoSubredditExistsErrorMsg(query);
          }
        }.bind(this),
        false, 'json', false, 
        function(e) {
          if (e === 'ratelimit') {
            // If ratelimited, try again in a bit
            if (typeof retries === 'undefined') {
              retries = 0;
            }
            if (retries > 3) {
              return this.srShowRequestFailedMsg();
            }
            window.setTimeout(
              r.srAutocomplete.srIsValidSubreddit.bind(
                this,
                query,
                successFn,
                retries + 1
              ),
              2000);
          } else {
            this.srShowRequestFailedMsg();
          }
        }.bind(this));
    },

    /**
    * Event handler for onkeyup 
    * Handles UI changes
    */
    srNameUp: function(e) {
      var newSrName = $('#sr-autocomplete').val();
      var oldSrName = this.oldSrName || '';
      this.oldSrName = newSrName;

      if (newSrName === '') {
        this.hideSrNameList();
      } else if (e.keyCode == this.KEYS.UP || 
          e.keyCode == this.KEYS.DOWN ||
          e.keyCode == this.KEYS.TAB) {
        // prevents the input value change from triggering srSearch
      } else if (e.keyCode == this.KEYS.ESCAPE && this.origSr) {
        $('#sr-autocomplete').val(this.origSr);
        this.hideSrNameList();
      } else if (newSrName != oldSrName) {
        this.origSr = newSrName;
        this.srSearch($('#sr-autocomplete').val());
      }
    },


    /* Event handler for onkeydown */
    srNameDown: function(e) {
      var input = $('#sr-autocomplete');
      
      if (e.keyCode == this.KEYS.UP || e.keyCode == this.KEYS.DOWN || e.keyCode == this.KEYS.TAB) {
        var dir = e.keyCode == this.KEYS.UP && 'up' || 'down';
        var curRow = $('#sr-drop-down .sr-selected:first');
        var firstRow = $('#sr-drop-down .sr-name-row:first');
        var lastRow = $('#sr-drop-down .sr-name-row:last');

        var newRow = null;
        if (dir == 'down' || e.keyCode == this.KEYS.TAB) {
          if (!curRow.length) {
            newRow = firstRow;
          } else if (curRow.get(0) == lastRow.get(0)) {
            newRow = null;
          } else {
            newRow = curRow.next(':first');
          }
        } else {
          if (!curRow.length) {
            newRow = lastRow;
          } else if (curRow.get(0) == firstRow.get(0)) {
            newRow = null;
          } else {
            newRow = curRow.prev(':first');
          }
        }
        this.highlightDropdownRow(newRow);
        if (newRow) {
          input.val($.trim(newRow.text()));
        } else {
          input.val(this.origSr);
        }
        return false;
      } else if (e.keyCode == this.KEYS.ENTER) {
        this.srIsValidSubreddit(
          e.target.value, 
          this.srAddSr(undefined, {subreddit: e.target.value}));
        if (this.isMultiple) {
          e.target.value = '';
        }
        this.hideSrNameList();
        return false;
      } else if (e.keyCode == this.KEYS.BACKSPACE) {
        if (!e.target.value && Object.keys(this.selectedSr).length !== 0) {
          e.preventDefault();
          var child = $('#sr-autocomplete-area > span').last();
          if (child) {
            var text = child.text();
            delete this.selectedSr[text];
            child.remove();
            this.srUpdateSelectedSrInput();
          }
          $('#sr-autocomplete').trigger('sr-changed', {deleteSubreddit: true});
        }
      }
    },

    hideSrNameList: function() {
      $('#sr-drop-down').hide();
    },

    /* UI: Highlights dropdown item
    @params {Event} e: event that triggered
    */
    highlightDropdown: function(e) {
      var item = e.target;
      r.srAutocomplete.highlightDropdownRow(item);
    },

    highlightDropdownRow: function(item) {  
      $('#sr-drop-down').children('.sr-selected').removeClass('sr-selected');
      if (item) {
        $(item).addClass('sr-selected');
      }
    },

    /* Event handler for when mousedown on the subreddit dropdown */
    srDropdownMdown: function(e) {
      r.srAutocomplete.srMouseRow = e.target; //global
      return false;
    },

    /* Event handler for when mouseup on the subreddit dropdown */
    srDropdownMup: function(e) {
      var row = e.target;
      if (this.srMouseRow == row) {
        var name = $(row).text();
        this.srIsValidSubreddit(
          name, 
          this.srAddSr(undefined, {isAutocomplete: true, subreddit: name}));
        if (this.isMultiple) {
          $('#sr-autocomplete').val('');
        }
        $('#sr-drop-down').hide();
      }
    },

    /* Called when a suggested subreddit is click */
    setSrName: function(e) {
      e.preventDefault();
      var link = e.target;
      var name = $(link).text();
      $('#sr-autocomplete').trigger('focus');
      this.srIsValidSubreddit(
        name, 
        this.srAddSr(undefined, {isSuggestion: true, subreddit: name}));
      return false;
    },

    /* UI: Adds a subreddit to the list of subreddits posted */
    srAddSr: function(srName, triggerParams) {
      var tooManySubreddits = Object.keys(this.selectedSr).length >= this.MAX_SUBREDDITS;
      var canAddToken = this.isMultiple &&
        srName &&
        !(srName.toLowerCase() in this.selectedSr) &&
        !(tooManySubreddits);
      // Checks if srName is defined and doesn't exist in selectedSr yet
      if (canAddToken) {
        var newSrToken = this.srToken(srName);
        $('#sr-autocomplete').before(newSrToken);
        this.selectedSr[srName] = true;
        this.srUpdateSelectedSrInput();
      } else if (srName && !this.isMultiple) {
        $('#sr-autocomplete').val(srName);
      } else if (!$.defined(srName)) {
        // partially fill the function. essentially the bind functionality
        return function(srName) {
          r.srAutocomplete.srAddSr(srName, triggerParams);
        }.bind(this);
      } else if (tooManySubreddits) {
        this.srShowTooManySubredditsMsg();
        return;
      }
      r.srAutocomplete.srHideErrorMsg();
      if ($.defined(triggerParams)) {
        $('#sr-autocomplete').trigger('sr-changed', triggerParams);
      } else {
        $('#sr-autocomplete').trigger('sr-changed');
      }
    },

    srReset: function() {
      this.selectedSr = {};
      var child = $('#sr-autocomplete-area > span').last();
      while (child.length !== 0) {
        child.remove();
        child = $('#sr-autocomplete-area > span').last();
      }
      this.srUpdateSelectedSrInput();
      $('#sr-autocomplete').trigger('sr-changed', {deleteSubreddit: true});
    },

    /**
    Displays an error message if a given subreddit is not valid
    */
    srShowNoSubredditExistsErrorMsg: function(subreddit) {
      var errorMsg = 'subreddit does not exist';
      if (subreddit) {
        errorMsg = 'subreddit /r/' + subreddit + ' does not exist';
      }
      r.srAutocomplete.srShowErrorMsg(errorMsg);
    },

    srShowTooManySubredditsMsg: function(){
      r.srAutocomplete.srShowErrorMsg(
        r._('the maximum number of subreddits you can target is %(num)s')
        .format({num: this.MAX_SUBREDDITS})
      );
    },

    srShowRequestFailedMsg: function(){
      var errorMsg = r._('something went wrong. please try again');
      return r.srAutocomplete.srShowErrorMsg(errorMsg);
    },

    srShowErrorMsg: function(errorMsg) {
      $('.SUBREDDIT_NOEXIST').text(errorMsg).show();
    },

    srHideErrorMsg: function() {
      $('.SUBREDDIT_NOEXIST').hide();
    },

    /**
    Handles removal of a subreddit from the selected subreddit list.

    Updates UI to reflect change.

    @params {Event} e: event of click

    @warning: Assumes a particular tree structure of the event. 
    Assumes the event only occurs when the close button is clicked

    */
    srRemoveSr: function(e) {
      $(e.target).parent().remove();
      delete this.selectedSr[e.target.previousSibling.nodeValue];
      this.srUpdateSelectedSrInput();
      $('#sr-autocomplete').trigger('sr-changed',{deleteSubreddit: true});
    },

    /**
    Updates input value of the subreddits submitted
    */
    srUpdateSelectedSrInput: function() {
      var newString = Object.keys(this.selectedSr).join(this.SR_NAMES_DELIM);
      $('#selected_sr_names').val(newString);
    },

    /**
    * UI effect to update dropdown
    **/
    srUpdateDropdown: function(srNames) {
      var dropDown = $('#sr-drop-down');
      if (!srNames.length) {
        dropDown.hide();
        return;
      }

      var firstRow = dropDown.children(':first');
      firstRow.removeClass('sr-selected');
      dropDown.children().remove();

      // Populates dropdown
      var j = 0;
      $.each(srNames, function(i) {
        if (srNames[i].toLowerCase() in this.selectedSr) return;
        if (j > 10) return;
        j++;
        var name = srNames[i];
        var $newRow = this.srDropdownRow(name);
        dropDown.append($newRow);
      }.bind(this));

      var height = $('#sr-autocomplete-area').outerHeight();
      dropDown.css('top', height);
      dropDown.show();
    },

    /** sr suggesting **/
    /**
    Clears the suggestion div
    */
    srSuggestionsClear: function() {
      $('#suggested-reddits').find('ul').empty();
      this.suggestedSr = {};
    },

    /**
    Resets the suggestions to the default subreddit suggestions
    */
    srSuggestionsReset: function() {
      this.srSuggestionsClear();
      for(var sr in this.defaultSuggestedSr) {
        this.srAddSuggestion(sr);
      }
    },

    /**
    Gets new suggestions and updates the UI with the data retrieved

    @params {Array} srNames: array of subreddit names to query
    @params {Boolean} reset: if true, clears the current suggestions before filling
    */
    srGetNewSuggestions: function(srNames, reset) {
      var selectedSr = $.map(this.selectedSr, function(i, v) {return v;});
      srNames = $.with_default(srNames, selectedSr);
      // Only want to seed the last NUM_SEED subreddits the user selected
      srNames = srNames.slice(Math.max(srNames.length - r.srAutocomplete.NUM_SEED, 0));
      reset = $.with_default(reset, true);
      $.when(this.srFetchSuggestions(srNames)).then(function(data) {
        if (reset) {r.srAutocomplete.srSuggestionsClear();}
        for(var i=0; i<data.length;i++) {
          r.srAutocomplete.srAddSuggestion(data[i].sr_name);
        }
      });
    },

    /**
    Adds one subreddit to the subreddit list
    */
    srAddSuggestion: function(srName) {
      if (!this.suggestedSr[srName]) {
        var newSuggestion = this.srSuggestion(srName);
        $('#suggested-reddits').find('ul').append(newSuggestion);
        this.suggestedSr[srName] = true;
      }
    },

    /**
    Adds all subreddits to the tokenizer
    */
    srAddAllSuggestions: function() {
      for(var suggestion in this.suggestedSr) {
        this.srAddSr(suggestion, {
          noNewSuggestions: true,
          subreddit: suggestion,
        });
      }
      $('#sr-autocomplete').trigger('sr-changed');
      return false;
    },

    /**
    Makes the API call to fetch suggestions
    */
    srFetchSuggestions: function(srNames) {
      if (typeof srNames === 'string') {
        srNames = [srNames];
      }
      return $.ajax(
        '/api/recommend/sr/' + srNames.join(r.srAutocomplete.SR_NAMES_DELIM),
        {
          type: 'GET',
          data: {
            over_18: false,
          },
          dataType: 'json',
        }
      );
    },

    /** Subreddit Hovercards **/

    /** Fetches a hovercard **/
    srGetHovercard: function(e) {
      var $link = $(e.target);
      var sr_name = $link.text();
      $.when(this.srFetchSubredditInfo(sr_name)).then(function(data) {
        this.srRemoveHovercard();
        var $hovercard = $(this.srHovercard(data));
        $link.before($hovercard);
        var top = 10 - $hovercard.height();
        $hovercard.css('top', top);
      }.bind(this));
    },

    /** Removes all hovercards **/
    srRemoveHovercard: function() {
      $('#suggested-reddits').find('.hovercard').remove();
    },

    srFetchSubredditInfo: function(sr_name) {
      if (this.srHovercardCache[sr_name]) {
        return this.srHovercardCache[sr_name];
      } else {
        return $.ajax(
          '/r/' + sr_name + '/about.json',
          {
            type: 'GET',
            dataType: 'json',
          }
          ).then(function(resp) {
            r.srAutocomplete.srHovercardCache[sr_name] = resp.data;
            return resp.data;
          });
      }
    },
  };
}(r, _, jQuery);

/** Deprecated event handlers. Inserted for backwards compatibility **/

function sr_name_up(e) {}

function sr_name_down(e) {}

function hide_sr_name_list(e) {}

function highlight_dropdown_row(item) {}

function sr_dropdown_mdown(row) {}

function sr_dropdown_mup(row) {}

function set_sr_name(link) {}

function sr_add_all_suggestions() {}
