!function(r) {

var RE_IS_MOBILE_PLATFORM = /^mobile(?:_(web|native))?$/;

var UseDefaultClassName = (function() {
  var camelCaseRegex = /([a-z])([A-Z])/g;
  function hyphenate(match, $1, $2) {
    return $1 + '-' + $2;
  }

  return {
    /**
     * derive a className automatically from the displayName property
     * e.g. MyDisplayName => my-display-name
     * if a className state or prop is passed in, add that
     * if values are passed into the function, add those in as well
     * @param {string} arguments optionally pass in any number of
     *                           classNames to to add to the list
     * @return {string} css class name
     */
    getClassName: function(/* classNames */) {
      var classNames = [];

      if (this.constructor.displayName) {
        classNames.push(
          this.constructor.displayName.replace(camelCaseRegex, hyphenate)
                                      .toLowerCase()
          );
      }

      if (this.state && this.state.className) {
        classNames.push(this.state.className);
      }
      else if (this.props.className) {
        classNames.push(this.props.className);
      }

      if (arguments.length) {
        classNames.push.apply(classNames, arguments);
      }

      return classNames.join(' ');
    }
  };
})();


var CampaignFormattedProps = {
  componentWillMount: function() {
    this.formattedProps = this.getFormattedProps(_.clone(this.props), this.props);
  },

  componentWillUpdate: function(nextProps) {
    this.formattedProps = this.getFormattedProps(_.clone(nextProps), nextProps);
  },

  getFormattedProps: function(formattedProps, props) {
    if (props.impressions) {
      formattedProps.impressions = r.utils.prettyNumber(props.impressions);
    }
    if (props.totalBudgetDollars === null) {
      formattedProps.totalBudgetDollars = 'N/A';
    } else if (_.isNaN(props.budget)) {
      formattedProps.totalBudgetDollars = 0;
    } else if (props.totalBudgetDollars) {
      formattedProps.totalBudgetDollars = props.totalBudgetDollars.toFixed(2);
    }
    return formattedProps;
  },
};

var CampaignButton = React.createClass({
  displayName: 'CampaignButton',

  mixins: [UseDefaultClassName],

  getDefaultProps: function() {
    return {
      isNew: true,
    };
  },

  render: function() {
    if (this.props.isNew) {
      return React.DOM.div({ className: 'button-group' },
        React.DOM.button(
          { ref: 'keepOpen', className: 'campaign-button', onClick: this.handleClick },
          r._('create')
        ),
        React.DOM.button(
          { className: this.getClassName(), onClick: this.handleClick },
          r._('+ close')
        ) 
      );
    }
    return React.DOM.button(
      { className: this.getClassName(), onClick: this.handleClick },
      this.props.isNew ? r._('create') : r._('save')
    );
  },

  handleClick: function(e) {
    var close = true;
    if (this.refs.keepOpen) {
      close = !(e.target === this.refs.keepOpen.getDOMNode());
    }
    if (typeof this.props.onClick === 'function') {
      this.props.onClick(close);
    }
  },
});

/*
React class that displays information and text
*/
var InfoText = React.createClass({
  displayName: 'InfoText',

  mixins: [UseDefaultClassName, CampaignFormattedProps],

  render: function() {
    var text = Array.isArray(this.props.children) ?
               this.props.children.join('\n') : this.props.children;
    return React.DOM.span({ className: this.getClassName() },
      text.format(this.formattedProps)
    );
  },

});

/**
* UI: Option that displays a CampaignOption object
*/
var CampaignOptionTable = React.createClass({
  displayName: 'CampaignOptionTable',

  mixins: [UseDefaultClassName],

  render: function() {
    return React.DOM.table({ className: this.getClassName() },
      React.DOM.tbody(null, this.props.children)
    );
  }
});

var CampaignOption = React.createClass({
  displayName: 'CampaignOption',

  mixins: [UseDefaultClassName, CampaignFormattedProps],

  getDefaultProps: function() {
    return {
      primary: false, // determines whether someone is able to create a new campaign
      start: '',
      end: '',
      bid: '',
      impressions: '',
      isNew: true,
      costBasis: '',
      totalBudgetDollars: '',
      bidDollars: '',
    };
  },

  render: function() {
    var customText;
    if (r.sponsored.isAuction) {
      customText = '$' + parseFloat(this.props.bidDollars).toFixed(2) + ' ' + this.props.costBasis;
    } else {
      customText = this.formattedProps.impressions + ' impressions';
    }
    return React.DOM.tr({ className: this.getClassName() },
      React.DOM.td({ className: 'date start-date' }, this.props.start),
      React.DOM.td({ className: 'date end-date' }, this.props.end),
      React.DOM.td({ className: 'total-budget' }, '$', this.formattedProps.totalBudgetDollars,
        ' total'),
      React.DOM.td({}, customText),
      React.DOM.td({ className: 'buttons' },
        CampaignButton({
          className: this.props.primary ? 'primary-button' : '',
          isNew: this.props.isNew,
          onClick: this.handleClick,
        })
      )
    );
  },
  /**
  * Handles the click and sends the form to server
  */
  handleClick: function(close) {
    var $startdate = $('#startdate');
    var $enddate = $('#enddate');
    var $totalBudgetDollars = $('#total_budget_dollars');
    var $bidDollars = $('#bid_dollars');
    var userStartdate = $startdate.val();
    var userEnddate = $enddate.val();
    var userTotalBudgetDollars = $totalBudgetDollars.val();
    var userBidDollars = $bidDollars.val() || 0.;
    $('#startdate').val(this.props.start);
    $('#enddate').val(this.props.end);
    $('#total_budget_dollars').val(this.props.totalBudgetDollars);
    $('#bid_dollars').val(this.props.bidDollars);
    setTimeout(function(){
      send_campaign(close);
      // hack, needed because post_pseudo_form hides any element in the form
      // with an `error` class, which might be one of our InfoText components
      // but we want react to manage that
      $('.campaign-creator .info-text').removeAttr('style');
      // reset the form with the user's original values
      $startdate.val(userStartdate);
      $enddate.val(userEnddate);
      $totalBudgetDollars.val(userTotalBudgetDollars);
      $bidDollars.val(userBidDollars);
    }, 0);
  },
});


var CampaignSet = React.createClass({
  displayName: 'CampaignSet',

  mixins: [UseDefaultClassName],

  render: function() {
    return React.DOM.div({ className: this.getClassName() },
      this.props.children
    );
  },
});

var CampaignCreator = React.createClass({
  displayName: 'CampaignCreator',

  mixins: [UseDefaultClassName],

  getDefaultProps: function() {
    return {
      totalBudgetDollars: 0,
      targetName: '',
      cpm: 0,
      minCpmBidDollars: 0,
      maxCpmBidDollars: 0,
      minCpcBidDollars: 0,
      maxCpcBidDollars: 0,
      maxBudgetDollars: 0,
      minBudgetDollars: 0,
      dates: [],
      inventory: [],
      requested: 0,
      override: false,
      isNew: true,
    };
  },

  getInitialState: function() {
    var totalAvailable = this.getAvailable(this.props);
    var available = totalAvailable;
    if (this.props.maxBudgetDollars) {
      available = Math.min(available, this.getImpressions(this.props.maxBudgetDollars));
    }
    return {
      totalAvailable: totalAvailable,
      available: available,
      maxTime: 0,
    };
  },

  componentWillMount: function() {
    this.setState({
      maxTime: dateFromInput('#date-start-max').getTime(),
    });
  },

  componentWillReceiveProps: function(nextProps) {
    var totalAvailable = this.getAvailable(nextProps);
    var available = totalAvailable;
    if (this.props.maxBudgetDollars) {
      available = Math.min(available, this.getImpressions(this.props.maxBudgetDollars));
    }
    this.setState({
      totalAvailable: totalAvailable,
      available: available,
    });
  },

  getAvailable: function(props) {
    if (props.override) {
      return _.reduce(props.inventory, sum, 0);
    }
    else {
      var inventory = _.filter(props.inventory, function(num){ return _.isFinite(num);});
      return _.min(inventory) * props.dates.length;
    }
  },

  render: function() {
    return React.DOM.div({
        className: this.getClassName(),
      },
      this.getCampaignSets()
    );
  },

  /**
  UI function that renders the campaign creation option based on user options and 
  available inventory.
  */
  getCampaignSets: function() {
    if (r.sponsored.isAuction) {
      var auction = this.getAuctionOption();

      var minBidDollars;
      var maxBidDollars;
      var validAuction = true;
      if (auction.costBasis === 'CPM') {
        minBidDollars = parseFloat(auction.minCpmBidDollars).toFixed(2);
        maxBidDollars = parseFloat(auction.maxCpmBidDollars).toFixed(2);
      } else if (auction.costBasis === 'CPC') {
        minBidDollars = parseFloat(auction.minCpcBidDollars).toFixed(2);
        maxBidDollars = parseFloat(auction.maxCpcBidDollars).toFixed(2);
      } else {
        validAuction = false;
      }

      var MESSAGES = {
            CONFIRM_MSG: r._('Please confirm the details of your campaign'),
            MIN_BUDGET_MSG: r._('your budget must be at least $%(minBudgetDollars)s'),
            MAX_BUDGET_MSG: r._('your budget must not exceed $%(maxBudgetDollars)s'),
            MIN_IMPRESSIONS_PER_DAY_MSG: r._('Your campaign must be capable of claiming at least' +
                                             ' 1,000 impressions per day. Please adjust your bid, ' +
                                             ' budget, or schedule in order to enable this.'),
            MIN_BID_MSG: r._('your bid must be at least $%(minBid)s'),
            MAX_BID_MSG: r._('your bid must not exceed $%(maxBid)s'),
            INVALID_AUCTION: r._('Something went wrong. Please refresh the page and try again.')
          };
      var INFOTEXT_ATTRS = {
            CONFIRM_MSG: null,
            MIN_BUDGET_MSG: {className: 'error', minBudgetDollars: auction.minBudgetDollars},
            MAX_BUDGET_MSG: {className: 'error', maxBudgetDollars: auction.maxBudgetDollars},
            MIN_IMPRESSIONS_PER_DAY_MSG: {className: 'error'},
            MIN_BID_MSG: {className: 'error', minBid: minBidDollars},
            MAX_BID_MSG: {className: 'error', maxBid: maxBidDollars},
            INVALID_AUCTION: null
          };
      var messageKey = "CONFIRM_MSG";

      if (!validAuction) {
        messageKey = "INVALID_AUCTION";
      } else if (auction.totalBudgetDollars < this.props.minBudgetDollars) {
        messageKey = "CONFIRM_MSG";
      } else if (auction.totalBudgetDollars > this.props.maxBudgetDollars &&
                 this.props.maxBudgetDollars > 0) {
        messageKey = "MIN_BUDGET_MSG";
      } else {
        if (r.sponsored.userIsSponsor) {
          auction.primary = true;
        } else if (auction.costBasis === 'CPM') {
          if (auction.maxCpmBidDollars < auction.minCpmBidDollars) {
            messageKey = "MIN_IMPRESSIONS_PER_DAY_MSG";
          } else if (auction.bidDollars < auction.minCpmBidDollars) {
            messageKey = "MIN_BID_MSG";
          } else if (auction.bidDollars > auction.maxCpmBidDollars) {
            messageKey = "MAX_BID_MSG";
          }
        } else if (auction.costBasis === 'CPC') {
          if (auction.bidDollars < auction.minCpcBidDollars) {
            messageKey = "MIN_BID_MSG";
          } else if (auction.bidDollars > auction.maxCpcBidDollars) {
            messageKey = "MAX_BID_MSG";
          }          
        } else {
          auction.primary = true;
        }
      }
      return [CampaignSet(null,
          InfoText(INFOTEXT_ATTRS[messageKey], MESSAGES[messageKey]),
          CampaignOptionTable(null, CampaignOption(auction))
        ),
      ];      
    } else {
      var requested = this.getRequestedOption(); // Options the user is asking for 
      var maximized = this.getMaximizedOption(); // Options the maximum available
      requested.primary = true;
      var MESSAGES = {
        IS_AVAILABLE_MSG: r._('the campaign you requested is available!'),
        MAX_BUDGET_AVAILABLE_MSG: r._('the maximum budget available is ' + 
                                      '$%(totalBudgetDollars)s (%(impressions)s impressions)'),
        MIGHT_NOT_DELIVER_MSG: r._('we expect to only have %(available)s impressions on %(target)s. ' +
                                    'we may not fully deliver.'),
        ADD_DIFFERENCE_MSG: r._('want to maximize your campaign? for only $%(difference)s more ' +
                                'you can buy all available inventory for your selected dates!'),
        CAMPAIGN_TOO_SMALL_MSG: r._('the campaign you requested is too small!'),
        CAMPAIGN_TOO_SMALL_OTHER_CAMPAIGN_MSG: r._('the campaign you requested is too small!' +
                                                  ' this campaign is available:'),
        CAMPAIGN_TOO_BIG_MSG: r._('the campaign you requested is too big! the largest campaign available is:'),
        INSUFFICIENT_INVENTORY_MSG: r._('we have insufficient available inventory targeting %(target)s to fulfill ' +
                                      'your requested dates. the following campaigns are available:'),
        NO_SUBREDDITS_SELECTED: r._('please select at least one subreddit'),
        SOLD_OUT_MSG: r._('inventory for %(target)s is sold out for your requested dates. ' +
                 'please try a different target or different dates.')
      };

      if (this.props.override) {
        if (requested.impressions <= this.state.available) {
          return [CampaignSet(null,
              InfoText(null, MESSAGES.IS_AVAILABLE_MSG),
              CampaignOptionTable(null, CampaignOption(requested))
            ),
            InfoText(maximized, MESSAGES.MAX_BUDGET_AVAILABLE_MSG)
          ];
        }
        else {
          return CampaignSet(null,
            InfoText({
                className: 'error',
                available: this.state.available,
                target: this.props.targetName
              }, MESSAGES.MIGHT_NOT_DELIVER_MSG),
            CampaignOptionTable(null, CampaignOption(requested))
          );
        }
      }
      else if (requested.totalBudgetDollars >= this.props.minBudgetDollars &&
               requested.impressions <= this.state.available) {
        var result = CampaignSet(null,
          InfoText(null, MESSAGES.IS_AVAILABLE_MSG),
          CampaignOptionTable(null, CampaignOption(requested))
        );
        var difference = maximized.totalBudgetDollars - requested.totalBudgetDollars;
        if (maximized.totalBudgetDollars > requested.totalBudgetDollars &&
            requested.totalBudgetDollars * 1.2 >= maximized.totalBudgetDollars &&
            this.state.available === this.state.totalAvailable) {
          result = [result, CampaignSet(null,
            InfoText({ difference: difference.toFixed(2) }, MESSAGES.ADD_DIFFERENCE_MSG),
            CampaignOptionTable(null, CampaignOption(maximized))
          )];
        } else {
          result = [result, InfoText(maximized, MESSAGES.MAX_BUDGET_AVAILABLE_MSG)];
        }
        return result;
      }
      else if (requested.totalBudgetDollars < this.props.minBudgetDollars) {
        var minimal = this.getMinimizedOption();
        if (minimal.impressions <= this.state.available) {
          if (r.sponsored.userIsSponsor) {
            return CampaignSet(null,
              InfoText(null, MESSAGES.IS_AVAILABLE_MSG),
              CampaignOptionTable(null, CampaignOption(requested))
            );
          } else {
            return CampaignSet(null,
              InfoText({ className: 'error'}, MESSAGES.CAMPAIGN_TOO_SMALL_OTHER_CAMPAIGN_MSG),
              CampaignOptionTable(null, CampaignOption(minimal))
            );
          }
        }
        else {
          return InfoText({ className: 'error' }, MESSAGES.CAMPAIGN_TOO_SMALL_MSG);
        }
      }
      else if (requested.impressions > this.state.available &&
               this.state.totalAvailable > this.state.available &&
               maximized.totalBudgetDollars > this.props.minBudgetDollars) {
        return CampaignSet(null,
          InfoText(null, MESSAGES.CAMPAIGN_TOO_BIG_MSG),
          CampaignOptionTable(null, CampaignOption(maximized))
        );
      }
      else if (requested.impressions > this.state.available) {
        /* Handles when impressions are greater than available
        Rather than let advertisers get frustrated, we display the best 
        options we could still sell them
        */
        r.analytics.fireFunnelEvent('ads', 'inventory-error');

        var options = [];
        if (maximized.totalBudgetDollars >= this.props.minBudgetDollars) {
          options.push(CampaignOption(maximized));
        }
        var reduced = this.getReducedWindowOption();
        if (reduced && reduced.totalBudgetDollars >= this.props.minBudgetDollars) {
          if (reduced.impressions > requested.impressions) {
            reduced.impressions = requested.impressions;
            reduced.totalBudgetDollars = requested.totalBudgetDollars;
          }
          options.push(CampaignOption(reduced));
        }
        if (options.length) {
          return CampaignSet(null,
            InfoText({
                className: 'error',
                target: this.props.targetName,
              }, MESSAGES.INSUFFICIENT_INVENTORY_MSG),
            CampaignOptionTable(null, options)
          );
        }
        else {
          return InfoText({ className: 'error', target: this.props.targetName},
                             MESSAGES.SOLD_OUT_MSG);
        }
      }
    }
    
    return null;
  },

  formatDate: function(date) {
    return $.datepicker.formatDate('mm/dd/yy', date);
  },

  getBudget: function(impressions, requestedBudget) {
    if (this.getImpressions(requestedBudget) === impressions) {
      return requestedBudget; 
    } else {
      return Math.floor((impressions / 1000) * this.props.cpm) / 100;
    }
  },

  getImpressions: function(bid) {
    return Math.floor(bid / this.props.cpm * 1000 * 100);
  },

  getOptionDates: function(startDate, duration) {
    if(!startDate){
      return {};
    }
    var endDate = new Date();
    endDate.setTime(startDate.getTime());
    endDate.setDate(startDate.getDate() + duration);
    return {
      start: this.formatDate(startDate),
      end: this.formatDate(endDate),
    };
  },

  getFixedCPMOptionData: function(startDate, duration, impressions, requestedBudget) {
    var dates = this.getOptionDates(startDate, duration);
    return {
      start: dates.start,
      end: dates.end,
      totalBudgetDollars: this.getBudget(impressions, requestedBudget),
      impressions: Math.floor(impressions),
      isNew: this.props.isNew,
    };
  },

  getAuctionOption: function() {
    var dates = this.getOptionDates(this.props.dates[0], this.props.dates.length);
    return {
      start: dates.start,
      end: dates.end,
      totalBudgetDollars: this.props.totalBudgetDollars,
      costBasis: this.props.costBasis,
      bidDollars: this.props.bidDollars,
      isNew: this.props.isNew,
      minCpmBidDollars: this.props.minCpmBidDollars,
      maxCpmBidDollars: this.props.maxCpmBidDollars,
      minCpcBidDollars: this.props.minCpcBidDollars,
      maxCpcBidDollars: this.props.maxCpcBidDollars,
      minBudgetDollars: this.props.minBudgetDollars,
      maxBudgetDollars: this.props.maxBudgetDollars
    };
  },

  getRequestedOption: function() {
    return this.getFixedCPMOptionData(
      this.props.dates[0],
      this.props.dates.length,
      this.props.requested,
      this.props.totalBudgetDollars
    );
  },

  getMaximizedOption: function() {
    return this.getFixedCPMOptionData(
      this.props.dates[0],
      this.props.dates.length,
      this.state.available,
      this.props.totalBudgetDollars
    );
  },

  getMinimizedOption: function() {
    return this.getFixedCPMOptionData(
      this.props.dates[0],
      this.props.dates.length,
      this.getImpressions(this.props.minBudgetDollars),
      this.props.minBudgetDollars
    );
  },

  getReducedWindowOption: function() {
    var days = (1000 * 60 * 60 * 24);
    var maxOffset = (this.state.maxTime - this.props.dates[0].getTime()) / days | 0;
    var res =  r.sponsored.getMaximumRequest(
      this.props.inventory,
      this.getImpressions(this.props.minBudgetDollars),
      this.props.requested,
      maxOffset
    );
    if (res && res.days.length < this.props.dates.length) {
      return this.getFixedCPMOptionData(
        this.props.dates[res.offset],
        res.days.length,
        res.maxRequest,
        this.props.totalBudgetDollars
      );
    }
    else {
      return null;
    }
  },
});


var exports = r.sponsored = {
    set_form_render_fnc: function(render) {
        this.render = render;
    },

    render: function() {},

    init: function() {
        this.targetValid = true;
        this.budgetValid = true;
        this.bidValid = true;
        this.inventory = {};
        this.campaignListColumns = $('.existing-campaigns thead th').length;
        $("input[name='media_url_type']").on("change", this.mediaInputChange);

        this.initUploads();
        this.instrumentCreativeFields();
    },

    initUploads: function() {
      function getEventData(payload, data) {
        return _.extend({}, payload, {
          kind: data.kind,
          link_id: data.link && parseInt(data.link, 36),
        });
      }

      $('.c-image-upload')
        .imageUpload()
        .on('attempt.imageUpload', function(e, data) {
          r.analytics.adsInteractionEvent('image_upload_attempt', getEventData({
            file_size: data.fileSize,
          }, data));
        })
        .on('success.imageUpload', function(e, data) {
          r.analytics.adsInteractionEvent('image_upload_success', getEventData({
            image_url: data.url,
          }, data));
        })
        .on('failed.imageUpload', function(e, data) {
          r.analytics.adsInteractionEvent('image_upload_failed', getEventData({
            reason: data.message,
          }, data));

          alert(data.message);
        })
        .on('openDialog.imageUpload', function(e, data) {
          r.analytics.adsInteractionEvent('image_open_dialog', getEventData({
            target: data.source,
          }, data));
        });
    },

    setup: function(inventory_by_sr, priceDict, isEmpty, userIsSponsor, forceAuction) {
        // external campaigns don't have an editor, skip setup.
        if (!$('#campaign').length) {
            return;
        }

        if (forceAuction) {
            this.isAuction = true;
        }
        this.inventory = inventory_by_sr;
        this.priceDict = priceDict;

        var $platformField = $('.platform-field');
        this.$platformInputs = $platformField.find('input[name=platform]');
        this.$mobileOSInputs = $platformField.find('.mobile-os-group input');
        this.$iOSDeviceInputs = $platformField.find('.ios-device input');
        this.$iOSMinSelect = $platformField.find('#ios_min');
        this.$iOSMaxSelect = $platformField.find('#ios_max');
        this.$androidDeviceInputs = $platformField.find('.android-device input');
        this.$androidMinSelect = $platformField.find('#android_min');
        this.$androidMaxSelect = $platformField.find('#android_max');
        this.$deviceAndVersionInputs = $platformField.find('input[name="os_versions"]');

        var render = this.render.bind(this);

        $('.platform-field input, .platform-field select').on('change', render);

        if (isEmpty) {
            this.render();
            init_startdate();
            init_enddate();
            $("#campaign").find("button[name=create]").show().end()
                .find("button[name=save]").hide().end();
        }

        this.userIsSponsor = userIsSponsor;

        $('[name=no_daily_budget]').on('change', render);
    },

    // UI. Counterpart is showCPMFields
    showAuctionFields: function() {
      $('.auction-field').show();
      $('.fixed-cpm-field').hide();
      $('.priority-field').hide();
      $('#is_auction_true').prop('checked', true);
    },

    // UI. Counterpart is setup AuctionFields:
    showCPMFields: function(){
      $('.auction-field').hide();
      $('.fixed-cpm-field').show();
      $('.priority-field').show();
      $('#is_auction_false').prop('checked', true);
    },

    setupLiveEditing: function(isLive) {
        var $budgetChangeWarning = $('.budget-unchangeable-warning');
        var $targetChangeWarning = $('.target-change-warning');
        if (isLive && !this.userIsSponsor) {
            $budgetChangeWarning.show();
            $targetChangeWarning.show();
            $('#total_budget_dollars').prop('disabled', true);
            $('#startdate').prop('disabled', true);
        } else {
            $budgetChangeWarning.hide();
            $targetChangeWarning.hide();
            $('#total_budget_dollars').removeAttr('disabled');
            $('#startdate').removeAttr('disabled');
        }
    },

    setup_collection_selector: function() {
        var $collectionSelector = $('.collection-selector');
        var $collectionList = $('.form-group-list');
        var $collections = $collectionList.find('.form-group .label-group');
        var collectionCount = $collections.length;
        var collectionHeight = $collections.eq(0).outerHeight();
        var $subredditList = $('.collection-subreddit-list ul');
        var $collectionLabel = $('.collection-subreddit-list .collection-label');
        var $frontpageLabel = $('.collection-subreddit-list .frontpage-label');

        var subredditNameTemplate = _.template('<% _.each(sr_names, function(name) { %>'
            + ' <li><%= name %></li> <% }); %>');
        var render_subreddit_list = _.bind(function(collection) {
            if (collection === 'none' || 
                    typeof this.collectionsByName[collection] === 'undefined') {
                return '';
            }
            else {
                return subredditNameTemplate(this.collectionsByName[collection]);
            }
        }, this);

        var collapse = _.bind(function(track) {
            this.collapse_collection_selector(track);
            this.render();
        }, this);

        var collapseAndTrack = _.partial(collapse, true);

        this.collapse_collection_selector = function collapse_widget(track) {
            $('body').off('click', collapseAndTrack);
            var $selected = get_selected();
            var index = $collections.index($selected);
            $collectionSelector.addClass('collapsed').removeClass('expanded');
            $collectionList.innerHeight(collectionHeight)
                .css('top', -collectionHeight * index);
            var val = $collectionList.find('input[type=radio]:checked').val();
            var subredditListItems = render_subreddit_list(val);
            $subredditList.html(subredditListItems);
            if (val === 'none') {
                $collectionLabel.hide();
                $frontpageLabel.show();
            }
            else {
                $collectionLabel.show();
                $frontpageLabel.hide();
            }

            if (track) {
              r.analytics.adsInteractionEvent('close_collections');
            }

        }

        function expand() {
            $('body').on('click', collapseAndTrack);
            $collectionSelector.addClass('expanded').removeClass('collapsed');
            $collectionList
                .innerHeight(collectionCount * collectionHeight)
                .css('top', 0);

            r.analytics.adsInteractionEvent('open_collections');
        }

        function get_selected() {
            return $collectionList.find('input[type=radio]:checked')
                .siblings('.label-group');
        }

        $collectionSelector
            .removeClass('uninitialized')
            .on('click', '.label-group', function(e) {
                if ($collectionSelector.is('.collapsed')) {
                    expand();
                }
                else {
                    var $selected = get_selected();
                    if ($selected[0] !== this) {
                        var $input = $(this).siblings('input');

                        $selected.siblings('input').prop('checked', false);
                        $input.prop('checked', 'checked');

                        r.analytics.adsInteractionEvent('select_collection', {
                          collection_name: $input.val() || 'frontpage',
                        });
                    }
                    collapse();
                }
                return false;
            });

        collapse();
    },

    instrumentCreativeFields: function() {
      var link_id36 = $('#promo-form [name=link_id36]').val();
      var link_id = link_id36 && parseInt(link_id36, 36);

      $('#kind-selector [name=kind]').on('change', function(e) {
        r.analytics.adsInteractionEvent('change_post_type', {
          link_id: link_id,
          post_type: $(e.target).val(),
        });
      });

      $('#title-field [name=title]').on('change', function(e) {
        r.analytics.adsInteractionEvent('change_title', {
          link_id: link_id,
          post_title: $(e.target).val(),
        });
      });

      $('#text-field [name=text]').on('change', function(e) {
        r.analytics.adsInteractionEvent('change_text', {
          link_id: link_id,
          post_text: $(e.target).val(),
        });
      });

      $('#url-field [name=url]').on('change', function(e) {
        r.analytics.adsInteractionEvent('change_url', {
          link_id: link_id,
          post_url: $(e.target).val(),
        });
      });

      $('#commenting-field [name="disable_comments"]').on('change', function(e) {
        r.analytics.adsInteractionEvent('change_disable_comments', {
          link_id: link_id,
          disable_comments: $(e.target).is(':checked'),
        });
      });

      $('#commenting-field [name="sendreplies"]').on('change', function(e) {
        r.analytics.adsInteractionEvent('change_sendreplies', {
          link_id: link_id,
          sendreplies: $(e.target).is(':checked'),
        });
      });
    },

    toggleFrequency: function() {
        var prevChecked = this.frequency_capped;
        var currentlyChecked = ($('input[name="frequency_capped"]:checked').val() === 'true');
        if (prevChecked != currentlyChecked) {
            $('.frequency-cap-field').toggle('slow');
            this.frequency_capped = currentlyChecked;
            this.render();
        }
    },

    toggleAuctionFields: function() {
        var prevChecked = this.isAuction;
        var currentlyChecked = ($('input[name="is_auction"]:checked').val() === 'true');
        if (prevChecked != currentlyChecked) {
            $('.auction-field').toggle();
            $('.fixed-cpm-field').toggle();
            $('.priority-field').toggle();
            this.isAuction = currentlyChecked;
            this.render();
        }
    },

    setup_frequency_cap: function(frequency_capped) {
        this.frequency_capped = !!frequency_capped;
    },

    setup_mobile_targeting: function(mobileOS, iOSDevices, iOSVersions, 
                                     androidDevices, androidVersions) {
      this.mobileOS = mobileOS;
      this.iOSDevices = iOSDevices;
      this.iOSVersions = iOSVersions;
      this.androidDevices = androidDevices;
      this.androidVersions = androidVersions;
    },

    setup_geotargeting: function(regions, metros) {
        this.regions = regions;
        this.metros = metros;
    },

    setup_collections: function(collections, defaultValue) {
        defaultValue = defaultValue || 'none';
        if(defaultValue.indexOf("/r/") > -1){
          // it's a multi subreddit disguising as a collection
          defaultValue = 'none';
        }

        this.collections = [{
            name: 'none', 
            sr_names: null, 
            description: 'influencers on reddit’s highest trafficking page',
        }].concat(collections || []);

        this.collectionsByName = _.reduce(collections, function(obj, item) {
            if (item.sr_names) {
                item.sr_names = item.sr_names.slice(0, 20);
            }
            obj[item.name] = item;
            return obj;
        }, {});

        var template = _.template('<label class="form-group">'
          + '<input type="radio" name="collection" value="<%= name %>"'
          + '    <% print(name === \'' + defaultValue + '\' ? "checked=\'checked\'" : "") %>/>'
          + '  <div class="label-group">'
          + '    <span class="label"><% print(name === \'none\' ? \'Reddit front page\' : name) %></span>'           
          + '    <small class="description"><%= description %></small>'
          + '  </div>'
          + '</label>');

        var rendered = _.map(this.collections, template).join('');
        $(_.bind(function() {
            $('.collection-selector .form-group-list').html(rendered);
            this.setup_collection_selector();
            this.render_campaign_dashboard_header();
        }, this));
    },

    // Sets up the subreddits on initialization
    setup_subreddits: function(srInput){
      if(typeof srInput === 'string'){
        if(srInput !== " reddit.com"){
          r.srAutocomplete.srAddSr(srInput);
        }
      } else if(typeof srInput === 'object'){
        var addSr = r.srAutocomplete.srAddSr(
          undefined,
          {
            noNewSuggestions: true,
          }
        );
        // check to make sure it's not the frontpage
        _.map(srInput, function(srName){
          addSr(srName);
        });
      }
    },

    get_dates: function(startdate, enddate) {
        var start = $.datepicker.parseDate('mm/dd/yy', startdate),
            end = $.datepicker.parseDate('mm/dd/yy', enddate),
            ndays = Math.round((end - start) / (1000 * 60 * 60 * 24)),
            dates = [];

        for (var i=0; i < ndays; i++) {
            var d = new Date(start.getTime());
            d.setDate(start.getDate() + i);
            dates.push(d);
        }
        return dates;
    },

    get_inventory_keys: function(srNames, collection, geotarget, platform) {
        var inventoryKeys = collection ? ['#' + collection] : srNames;
        if(inventoryKeys.length === 0){
          // frontpage
          inventoryKeys = [" reddit.com"];
        }

        inventoryKeys = inventoryKeys.map(function(s){
          return r.sponsored.append_geotarget_and_platform(s, geotarget, platform);
        });
        return inventoryKeys;
    },

    append_geotarget_and_platform: function(inventoryKey, geotarget, platform) {
      inventoryKey += "/" + platform;
      var c = "";
      if (geotarget.country !== "") {
        inventoryKey += "/" + geotarget.country;
      }
      if (geotarget.metro !== "") {
        inventoryKey += "/" + geotarget.metro;
      }
      return inventoryKey;
    },

    /**
    Determines whether to fetch inventory

    @param {String} targeting: type of targeting ('one', 'collection')
    @param {Object} timing: object with the timings of campaign. 
      @reference function get_timing


    @returns {Boolean}: whether there needs an API call to inventory 
      @reference function get_check_inventory

    */
    needs_to_fetch_inventory: function(targeting, timing) {
        var dates = timing.dates,
            inventoryKeys = targeting.inventoryKeys;
        return this.targetDirty && _.some(inventoryKeys, function(inventoryKey){ 
            return _.some(dates, function(date) {
              var datestr = $.datepicker.formatDate('mm/dd/yy', date);
              if (_.has(r.sponsored.inventory, inventoryKey) && 
                  _.has(r.sponsored.inventory[inventoryKey], datestr)) {
                  return false;
              }
              else {
                  r.debug('need to fetch ' + datestr + ' for ' + inventoryKey);
                  return true;
              }
          }, this);
        });
    },

    get_check_inventory: function(targeting, timing) {
        if (this.needs_to_fetch_inventory(targeting, timing)) {
            this.render_disabled_form("Fetching Inventory ...");
            var srname = targeting.srString,
                collection = targeting.collection,
                geotarget = targeting.geotarget,
                platform = targeting.platform,
                inventoryKeys = targeting.inventoryKeys,
                dates = timing.dates;

            dates.sort(function(d1,d2){return d1 - d2;});
            var end = new Date(dates[dates.length-1].getTime());
            end.setDate(end.getDate() + 5);
            return $.request(
              "check_inventory.json",
              {
                sr: srname,
                collection: collection,
                country: geotarget.country,
                region: geotarget.region,
                metro: geotarget.metro,
                startdate: $.datepicker.formatDate('mm/dd/yy', dates[0]),
                enddate: $.datepicker.formatDate('mm/dd/yy', end),
                platform: platform
              },
              // worker
              function(data) {
                  data = data.inventory;
                  for (var dataKey in data) {
                      // skip loop if the property is from prototype
                      if (!data.hasOwnProperty(dataKey)) continue;

                      // data comes from controller and is platform blind
                      // inventory comes from r.sponsored.inventory and is 
                      // platform specific
                      var inventoryKey = r.sponsored.append_geotarget_and_platform(
                            dataKey.toLowerCase(),
                            targeting.geotarget,
                            targeting.platform);
                      if (!r.sponsored.inventory[inventoryKey]) {
                        r.sponsored.inventory[inventoryKey] = {};
                      }
                      for (var datestr in data[dataKey]) {
                        if (!r.sponsored.inventory[inventoryKey][datestr]) {
                          r.sponsored.inventory[inventoryKey][datestr] = data[dataKey][datestr];
                        }
                      }
                  }
                  r.sponsored.lastFetchedTarget = targeting;
                  r.sponsored.targetDirty = false;
                  // Intended to rerender the campaign to update info
                  r.sponsored.render();
              }, true, "json", true
            );
        } else {
            return true;
        }
    },

    get_booked_inventory: function($form, srname, geotarget, isOverride) {
        var campaign_name = $form.find('input[name="campaign_name"]').val()
        if (!campaign_name) {
            return {}
        }

        var $campaign_row = $('.existing-campaigns .' + campaign_name)
        if (!$campaign_row.length) {
            return {}
        }

        if (!$campaign_row.data('paid')) {
            return {}
        }

        var existing_srname = $campaign_row.data("targeting")
        if (srname != existing_srname) {
            return {}
        }

        var existing_country = $campaign_row.data("country")
        if (geotarget.country != existing_country) {
            return {}
        }

        var existing_metro = $campaign_row.data("metro")
        if (geotarget.metro != existing_metro) {
            return {}
        }

        var existingOverride = $campaign_row.data("override")
        if (isOverride != existingOverride) {
            return {}
        }

        var startdate = $campaign_row.data("startdate"),
            enddate = $campaign_row.data("enddate"),
            dates = this.get_dates(startdate, enddate),
            bid = $campaign_row.data("bid"),
            cpm = $campaign_row.data("cpm"),
            ndays = this.duration_from_dates(startdate, enddate),
            impressions = this.calc_impressions(bid, cpm),
            daily = Math.floor(impressions / ndays),
            booked = {}

        _.each(dates, function(date) {
            var datestr = $.datepicker.formatDate('mm/dd/yy', date)
            booked[datestr] = daily
        })
        return booked

    },

    /**
    Returns an array of available impressions by day

    @params {Array} dates: dates to query
    @params {Object} booked: amount of booked impressions
    @params {String} inventoryKeys: key of the subreddit/collection and dates we're targeting

    @returns {Array} array of available impressions ordered by day
    */
    getAvailableImpsByDay: function(dates, booked, inventoryKeys) {
        return _.map(dates, function(date) {
            var datestr = $.datepicker.formatDate('mm/dd/yy', date);
            var total = 0;
            // iterate through 
            for (var i = 0; i < inventoryKeys.length; i++) {
              var daily_booked = $.with_default(booked[datestr], 0);
              var inventoryKey = inventoryKeys[i];
              if(r.sponsored.inventory[inventoryKey]){
                total += r.sponsored.inventory[inventoryKey][datestr] + daily_booked;
              }
            }
            return total;
        });
    },

    setup_auction: function($form, targeting, timing) {
        var dates = timing.dates,
            totalBudgetDollars = parseFloat($("#total_budget_dollars").val()),
            costBasisValue = $form.find('#cost_basis').val(),
            bidDollars = $form.find('#bid_dollars').val() || 0.,
            minCpmBidDollars = r.sponsored.get_min_cpm_bid_dollars(),
            maxCpmBidDollars = r.sponsored.get_lowest_max_cpm_bid_dollars($form),
            minCpcBidDollars = r.sponsored.get_min_cpc_bid_dollars(),
            maxCpcBidDollars = r.sponsored.get_max_cpc_bid_dollars(),
            minBudgetDollars = r.sponsored.get_min_budget_dollars(),
            maxBudgetDollars = r.sponsored.get_max_budget_dollars();

        React.renderComponent(
          CampaignCreator({
            totalBudgetDollars: totalBudgetDollars,
            dates: dates,
            isNew: $form.find('#is_new').val() === 'true',
            minCpmBidDollars: minCpmBidDollars,
            maxCpmBidDollars: maxCpmBidDollars,
            minCpcBidDollars: minCpcBidDollars,
            maxCpcBidDollars: maxCpcBidDollars,
            maxBudgetDollars: parseFloat(maxBudgetDollars),
            minBudgetDollars: parseFloat(minBudgetDollars),
            targetName: targeting.displayName,
            targeting: targeting,
            costBasis: costBasisValue.toUpperCase(),
            bidDollars: parseFloat(bidDollars),
          }),
          document.getElementById('campaign-creator')
        );
    },

    /**
    * Sets up campaigns for house ads
    */
    setup_house: function($form, targeting, timing, isOverride) {
      $.when(r.sponsored.get_check_inventory(targeting, timing)).then(
        function() {
          var booked = this.get_booked_inventory($form, targeting.sr,
                                                 targeting.geotarget, isOverride);
          var availableByDate = this.getAvailableImpsByDay(timing.dates, booked,
                                                           targeting.inventoryKeys);
          var totalImpsAvailable = _.reduce(availableByDate, sum, 0);

          React.renderComponent(
            React.DOM.div(null,
              CampaignSet(null,
                InfoText(null, r._('house campaigns, man.')),
                CampaignOptionTable(null,
                  CampaignOption({
                    bid: null,
                    end: timing.enddate,
                    impressions: 'unsold ',
                    isNew: $form.find('#is_new').val() === 'true',
                    primary: true,
                    start: timing.startdate,
                  })
                )
              ),
              InfoText({impressions: totalImpsAvailable},
                  r._('maximum possible impressions: %(impressions)s')
              )
            ),
            document.getElementById('campaign-creator')
          );
        }.bind(this)
      );

    },

    check_inventory: function($form, targeting, timing, budget, isOverride) {
        var totalBudgetDollars = budget.totalBudgetDollars,
            cpm = budget.cpm,
            requested = budget.impressions,
            daily_request = Math.floor(requested / timing.duration),
            inventoryKeys = targeting.inventoryKeys,
            booked = this.get_booked_inventory($form, targeting.sr, 
                    targeting.geotarget, isOverride),
            minBudgetDollars = r.sponsored.get_min_budget_dollars(),
            maxBudgetDollars = r.sponsored.get_max_budget_dollars();

        $.when(r.sponsored.get_check_inventory(targeting, timing)).then(
            function() {
                var dates = timing.dates;
                var availableByDay = this.getAvailableImpsByDay(dates, booked, inventoryKeys);
                React.renderComponent(
                  CampaignCreator({
                    totalBudgetDollars: totalBudgetDollars,
                    cpm: cpm,
                    dates: timing.dates,
                    inventory: availableByDay,
                    isNew: $form.find('#is_new').val() === 'true',
                    maxBudgetDollars: parseFloat(maxBudgetDollars),
                    minBudgetDollars: parseFloat(minBudgetDollars),
                    override: isOverride,
                    requested: requested,
                    targetName: targeting.displayName,
                  }),

                  document.getElementById('campaign-creator')
                );
            }.bind(this),
            function () {
                React.renderComponent(
                  CampaignSet(null,
                    InfoText(null,
                      r._('sorry, there was an error retrieving available impressions. ' +
                           'please try again later.')
                    )
                  ),
                  document.getElementById('campaign-creator')
                );
            }
        );
    },

    duration_from_dates: function(start, end) {
        return Math.round((Date.parse(end) - Date.parse(start)) / (86400*1000));
    },

    get_total_budget: function($form) {
        return parseFloat($form.find('*[name="total_budget_dollars"]').val()) || 0;
    },

    get_cpm: function($form) {
        var isMetroGeotarget = $('#metro').val() !== null && !$('#metro').is(':disabled');
        var metro = $('#metro').val();
        var country = $('#country').val();
        var isGeotarget = country !== '' && !$('#country').is(':disabled');
        var isSubreddit = $form.find('input[name="targeting"][value="subreddit"]').is(':checked');
        var collectionVal = $form.find('input[name="collection"]:checked').val();
        var isFrontpage = !isSubreddit && collectionVal === 'none';
        var isCollection = !isSubreddit && !isFrontpage;
        var sr = isSubreddit ? $form.find('*[name="sr"]').val() : '';
        var collection = isCollection ? collectionVal : null;
        var prices = [];

        if (isMetroGeotarget) {
            var metroKey = metro + country;
            prices.push(this.priceDict.METRO[metro] || this.priceDict.METRO_DEFAULT);
        } else if (isGeotarget) {
            prices.push(this.priceDict.COUNTRY[country] || this.priceDict.COUNTRY_DEFAULT);
        }

        if (isFrontpage) {
            prices.push(this.priceDict.COLLECTION_DEFAULT);
        } else if (isCollection) {
            prices.push(this.priceDict.COLLECTION[collectionVal] || this.priceDict.COLLECTION_DEFAULT);
        } else {
            prices.push(this.priceDict.SUBREDDIT[sr] || this.priceDict.SUBREDDIT_DEFAULT);
        }

        return _.max(prices);
    },

    getPlatformTargeting: function() {
      var platform = this.$platformInputs.filter(':checked').val();
      var isMobile = RE_IS_MOBILE_PLATFORM.test(platform) || platform === 'all';

      function mapTargets(target) {
        targets = target.filter(':checked').map(function() {
          return $(this).attr('value');
        }).toArray().join(',');
        return targets.length === 1 ? targets[0] : targets
      }

      function getSelect(target) {
        return target.find(':selected').val();
      }

      var targets;
      if (isMobile) {
        targets = {
          os: mapTargets(this.$mobileOSInputs),
          deviceAndVersion: mapTargets(this.$deviceAndVersionInputs),
          iOSDevices: mapTargets(this.$iOSDeviceInputs),
          iOSVersionRange: (getSelect(this.$iOSMinSelect) + ','
            + getSelect(this.$iOSMaxSelect)),
          iOSMinVersion: getSelect(this.$iOSMinSelect),
          iOSMaxVersion: getSelect(this.$iOSMaxSelect),
          androidDevices: mapTargets(this.$androidDeviceInputs),
          androidVersionRange: (getSelect(this.$androidMinSelect) + ','
            + getSelect(this.$androidMaxSelect)),
          androidMinVersion: getSelect(this.$androidMinSelect),
          androidMaxVersion: getSelect(this.$androidMaxSelect),
        };
      } else {
        targets = {
          os: null,
          deviceAndVersion: null,
          iOSDevices: null,
          iOSVersionRange: null,
          iOSMinVersion: null,
          iOSMaxVersion: null,
          androidDevices: null,
          androidVersionRange: null,
          androidMinVersion: null,
          androidMaxVersion: null,
        };
      }

      return $.extend({
        platform: platform,
        isMobile: isMobile,
      }, targets);
    },

    get_targeting: function($form) {
        var isSubreddit = $form.find('input[name="targeting"][value="subreddit"]').is(':checked'),
            collectionVal = $form.find('input[name="collection"]:checked').val(),
            isFrontpage = !isSubreddit && collectionVal === 'none',
            isCollection = !isSubreddit && !isFrontpage,
            type = isFrontpage ? 'frontpage' : isCollection ? 'collection' : 'subreddit',
            srString = $form.find("#selected_sr_names").val(),
            sr = isSubreddit && !!srString ? r.srAutocomplete.getSelectedSubreddits() : [],
            collection = isCollection ? collectionVal : null,
            canGeotarget = isFrontpage || this.userIsSponsor || this.isAuction,
            country = canGeotarget && $('#country').val() || '',
            region = canGeotarget && $('#region').val() || '',
            metro = canGeotarget && $('#metro').val() || '',
            geotarget = {'country': country, 'region': region, 'metro': metro},
            timing = this.get_timing($form),
            inventoryKeys = this.get_inventory_keys(sr, collection, geotarget, platform),
            isValid = isFrontpage || 
                      (isSubreddit && (sr.length > 0) 
                        && !$("#sr-autocomplete").prop("disabled")) || 
                      (isCollection && collection);

        var displayName;
        switch(type) {
            case 'frontpage':
                displayName = 'the frontpage';
                break;
            case 'subreddit':
                displayName = sr.length == 1 ? 
                              '/r/' + sr : sr.map(function(s){return '/r/' + s;}).join("\n");
                break;
            default:
                displayName = collection
        }

        if (canGeotarget) {
            var geoStrings = []
            if (country) {
                if (region) {
                    if (metro) {
                        var metroName = $('#metro option[value="'+metro+'"]').text()
                        // metroName is in the form 'metro, state abbreviation';
                        // since we want 'metro, full state', split the metro
                        // from the state, then add the full state separately
                        geoStrings.push(metroName.split(',')[0])
                    }
                    var regionName = $('#region option[value="'+region+'"]').text()
                    geoStrings.push(regionName)
                }
                var countryName = $('#country option[value="'+country+'"]').text()
                geoStrings.push(countryName)
            }

            if (geoStrings.length > 0) {
                displayName += ' in '
                displayName += geoStrings.join(', ')
            }
        }

        var target = {
            'type': type,
            'displayName': displayName,
            'isValid': isValid,
            'srString': srString,
            'sr': sr,
            'collection': collection,
            'canGeotarget': canGeotarget,
            'geotarget': geotarget,
            'timing': timing,
        };

        if (this.$platformInputs) {
            var platformTargets = this.getPlatformTargeting();

            var os = platformTargets.os;
            var platform = platformTargets.platform;
            var iOSDevices = platformTargets.iOSDevices;
            var iOSVersionRange = platformTargets.iOSVersionRange;
            var androidDevices = platformTargets.androidDevices;
            var androidVersionRange = platformTargets.androidVersionRange;
            
            platformTargetsList = ['platform',
                                   'iOSDevices',
                                   'iOSVersionRange',
                                   'androidDevices',
                                   'androidVersionRange',];

            platformTargetsList.forEach(function(platformStr) {
              target[platformStr] = eval(platformStr)
            });

            target.inventoryKeys = this.get_inventory_keys(sr, collection, geotarget, platform);
        } else {
            target.inventoryKeys = this.get_inventory_keys(sr, collection, geotarget);
        }

        if(this.lastFetchedTarget === undefined){
          this.lastFetchedTarget = {};
        }
        
        if(!_.isEqual(this.lastFetchedTarget, target)){
          // check inventory if target has changed
          this.targetDirty = true;
        }
        return target;
    },

    get_timing: function($form) {
        var startdate = $form.find('*[name="startdate"]').val(),
            enddate = $form.find('*[name="enddate"]').val(),
            duration = this.duration_from_dates(startdate, enddate),
            dates = r.sponsored.get_dates(startdate, enddate);

        return {
            'startdate': startdate,
            'enddate': enddate,
            'duration': duration,
            'dates': dates,
        }
    },

    get_budget: function($form) {
        var totalBudgetDollars = this.get_total_budget($form),
            cpm = this.get_cpm($form),
            impressions = this.calc_impressions(totalBudgetDollars, cpm);

        return {
            'totalBudgetDollars': totalBudgetDollars,
            'cpm': cpm,
            'impressions': impressions,
        };
    },

    get_priority: function($form) {
        var priority = $form.find('*[name="priority"]:checked'),
            isOverride = priority.data("override"),
            isHouse = priority.data("house");

        return {
            isOverride: isOverride,
            isHouse: isHouse,
        };
    },


    get_reporting: function($form) {
        var link_text = $form.find('[name=link_text]').val(),
            owner = $form.find('[name=owner]').val();

        return {
            link_text: link_text,
            owner: owner,
        };
    },

    get_campaigns: function($list, $form) {
        var campaignRows = $list.find('.existing-campaigns tbody tr').toArray();
        var collections = this.collectionsByName;
        var fixedCPMCampaigns = 0;
        var fixedCPMSubreddits = {};
        var totalFixedCPMBudgetDollars = 0;
        var auctionCampaigns = 0;
        var auctionSubreddits = {};
        var totalAuctionBudgetDollars = 0;
        var totalImpressions = 0;

        function mapSubreddit(name, subreddits) {
            subreddits[name] = 1;
        }

        function getSubredditsByCollection(name) {
            return collections[name] && collections[name].sr_names || null;
        }

        function mapCollection(name, subreddits) {
            var subredditNames = getSubredditsByCollection(name);
            if(!subredditNames){
              subredditNames = extract_subreddits_from_str(name);
            }
            _.each(subredditNames, function(subredditName) {
                mapSubreddit(subredditName, subreddits);
            });
        }

        _.each(campaignRows, function(row) {
            var data = $(row).data();
            var isCollection = (data.targetingCollection === 'True');
            var countSubredditsFn = isCollection ? mapCollection : mapSubreddit;
            var budget = parseFloat(data.total_budget_dollars, 10);

            if (data.is_auction === 'True') {
                auctionCampaigns++;
                countSubredditsFn(data.targeting, auctionSubreddits);
                totalAuctionBudgetDollars += budget;
            } else {
                fixedCPMCampaigns++;
                countSubredditsFn(data.targeting, fixedCPMSubreddits);
                totalFixedCPMBudgetDollars += budget;
                var bid = data.bid_dollars;
                var impressions = Math.floor(budget / bid * 1000);
                totalImpressions += impressions;
            }
        });

        return {
            count: campaignRows.length,
            fixedCPMCampaigns: fixedCPMCampaigns,
            auctionCampaigns: auctionCampaigns,
            fixedCPMSubreddits: fixedCPMSubreddits,
            auctionSubreddits: _.keys(auctionSubreddits),
            fixedCPMSubreddits: _.keys(fixedCPMSubreddits),
            prettyTotalAuctionBudgetDollars: '$' + totalAuctionBudgetDollars.toFixed(2),
            prettyTotalFixedCPMBudgetDollars: '$' + totalFixedCPMBudgetDollars.toFixed(2),
            totalImpressions: r.utils.prettyNumber(totalImpressions),
        };
    },

    auction_dashboard_help_template: _.template('<p>there '
        + '<% auctionCampaigns > 1 ? print("are") : print("is") %> '
        + '<%= auctionCampaigns %> auction campaign'
        + '<% auctionCampaigns > 1 && print("s") %> with a total budget of '
        + '<%= prettyTotalAuctionBudgetDollars %> in '
        + '<%= auctionSubreddits.length %> subreddit'
        + '<% auctionSubreddits.length > 1 && print("s") %></p>'),

    fixed_cpm_dashboard_help_template: _.template('<p>there '
        + '<% fixedCPMCampaigns > 1 ? print("are") : print("is") %> '
        + '<%= fixedCPMCampaigns %> fixed CPM campaign'
        + '<% fixedCPMCampaigns > 1 && print("s") %> with a total budget of '
        + '<%= prettyTotalFixedCPMBudgetDollars %> in '
        + '<%= fixedCPMSubreddits.length %> subreddit'
        + '<% fixedCPMSubreddits.length > 1 && print("s") %>, amounting to a '
        + 'total of <%= totalImpressions %> impressions</p>'),

    render_campaign_dashboard_header: function() {
        var $form = $("#campaign");
        var campaigns = this.get_campaigns($('.campaign-list'), $form);
        var $campaignDashboardHeader = $('.campaign-dashboard header');
        if (campaigns.count) {
            var templateText = '';
            if (campaigns.auctionCampaigns > 0) {
                templateText += this.auction_dashboard_help_template(campaigns);
            }
            if (campaigns.fixedCPMCampaigns > 0) {
                templateText += this.fixed_cpm_dashboard_help_template(campaigns);
            }
            $campaignDashboardHeader
                .find('.help').show().html(templateText).end()
                .find('.error').hide();
        }
        else {
            $campaignDashboardHeader
                .find('.error').show().end()
                .find('.help').hide();
        }
    },

    on_date_change: function() {
        this.render()
    },

    on_bid_change: function() {
        this.render()
    },

    on_cost_basis_change: function() {
        this.render();
    },

    on_budget_change: function() {
        this.render()
    },

    on_impression_change: function() {
        var $form = $("#campaign"),
            cpm = this.get_cpm($form),
            impressions = parseInt($form.find('*[name="impressions"]').val().replace(/,/g, "") || 0),
            totalBudgetDollars = this.calc_budget_dollars_from_impressions(impressions, cpm),
            $totalBudgetDollars = $form.find('*[name="total_budget_dollars"]')
        $totalBudgetDollars.val(totalBudgetDollars)
        $totalBudgetDollars.trigger("change")
    },

    on_frequency_cap_change: function() {
        this.render();
    },

    validateDeviceAndVersion: function(os, generalData, osData) {
      var deviceError = false;
      var versionError = false;
      /* if OS is selected to target, populate hidden inputs */
      if (generalData.platformTargetingOS.indexOf(os) !== -1) {
        osData.deviceHiddenInput.val(osData.platformTargetingDevices);
        osData.versionHiddenInput.val(osData.platformTargetingVersions);
        osData.group.show();

        if (generalData.deviceAndVersion == 'filter') {
          /* check that at least one devices is selected */
          if (!osData.deviceHiddenInput.val()) {
            deviceError = true;
          }

          /* check that min version is less-or-equal-to max */
          var versions = osData.versionHiddenInput.val().split(',');
          if ((versions[1] !== '') && (versions[0] > versions[1])) {
            versionError = true;
          }
        }
      } else {
        osData.deviceHiddenInput.val('');
        osData.versionHiddenInput.val('');
        osData.group.hide();
      }
      return {'deviceError': deviceError,
              'versionError': versionError}
    },

    /** 
    * render function for promotelinkbase.html
    * 
    * render() is called every time something is changed
    */
    fill_campaign_editor: function() {
        var $form = $("#campaign");

        // external campaigns don't have an editor.
        if (!$form.length) {
          return;
        }

        var platformTargeting = this.getPlatformTargeting();

        this.currentPlatform = platformTargeting.platform;

        var priority = this.get_priority($form),
            targeting = this.get_targeting($form),
            timing = this.get_timing($form),
            ndays = timing.duration,
            budget = this.get_budget($form),
            cpm = budget.cpm,
            impressions = budget.impressions,
            isValidForm = false; // Checks to see if we would let user submit form

        this.targetValid = targeting.isValid;

        var durationInDays = ndays + " " + ((ndays > 1) ? r._("days") : r._("day"))
        $(".duration").text(durationInDays)
        var totalBudgetDollars = parseFloat($("#total_budget_dollars").val())
        var dailySpend = totalBudgetDollars / parseInt(durationInDays)
        $(".daily-max-spend").text((isNaN(dailySpend) ? 0.00 : dailySpend).toFixed(2));

        $(".price-info").text(r._("$%(cpm)s per 1,000 impressions").format({cpm: (cpm/100).toFixed(2)}))
        $form.find('*[name="impressions"]').val(r.utils.prettyNumber(impressions))
        $(".OVERSOLD").hide()

        var costBasisValue = $form.find('#cost_basis').val();
        var $costBasisLabel = $form.find('.cost-basis-label');
        var $pricingMessageDiv = $form.find('.pricing-message');

        var pricingMessage = (costBasisValue === 'cpc') ? 'click' : '1,000 impressions';

        $costBasisLabel.text(costBasisValue);
        $pricingMessageDiv.text('Set how much you\'re willing to pay per ' + pricingMessage);

        var $mobileOSGroup = $('.mobile-os-group');
        var $mobileOSHiddenInput = $('#mobile_os');

        var $OSDeviceGroup = $('.os-device-group');
        var $iOSDeviceHiddenInput = $('#ios_device');
        var $iOSVersionHiddenInput = $('#ios_version_range');
        var $androidDeviceHiddenInput = $('#android_device');
        var $androidVersionHiddenInput = $('#android_version_range');

        if (platformTargeting.isMobile) {
          var $mobileOSError = $mobileOSGroup.find('.error');
          var $OSDeviceError = $OSDeviceGroup.find('.error.device-error');
          var $OSVersionError = $OSDeviceGroup.find('.error.version-error');

          $mobileOSGroup.show();
          $mobileOSHiddenInput.val(platformTargeting.os || '');

          $OSDeviceGroup.show();

          if (!platformTargeting.os) {
            $mobileOSError.show();
          } else {
            $mobileOSError.hide();
          }

          var $deviceVersionGroup = $('.device-version-group');
          var $deviceAndVersion = (platformTargeting.deviceAndVersion || 'all')

          if ($deviceAndVersion === 'all') {
            $deviceVersionGroup.hide();
            $OSDeviceError.hide();
            $OSVersionError.hide();
            $iOSDeviceHiddenInput.val('');
            $iOSVersionHiddenInput.val('');
            $androidDeviceHiddenInput.val('');
            $androidVersionHiddenInput.val('');
          } else {
            $deviceVersionGroup.show();

            $iOSGroup = $('.ios-group');
            $androidGroup = $('.android-group');

            var generalData = {
              platformTargetingOS: platformTargeting.os,
              deviceAndVersion: $deviceAndVersion,
            }

            var iOSData = {
              deviceHiddenInput: $iOSDeviceHiddenInput,
              versionHiddenInput: $iOSVersionHiddenInput,
              platformTargetingDevices: platformTargeting.iOSDevices,
              platformTargetingVersions: platformTargeting.iOSVersionRange,
              group: $iOSGroup,
            }

            var androidData = {
              deviceHiddenInput: $androidDeviceHiddenInput,
              versionHiddenInput: $androidVersionHiddenInput,
              platformTargetingDevices: platformTargeting.androidDevices,
              platformTargetingVersions: platformTargeting.androidVersionRange,
              group: $androidGroup,
            }

            var iOSErrors = this.validateDeviceAndVersion('iOS', generalData, iOSData);
            var androidErrors = this.validateDeviceAndVersion('Android', generalData, androidData);
            var iOSDeviceError = iOSErrors['deviceError']
            var iOSVersionError = iOSErrors['versionError'];
            var androidDeviceError = androidErrors['deviceError'];
            var androidVersionError = androidErrors['versionError'];

            if (iOSDeviceError || androidDeviceError) {
              $OSDeviceError.show();
            } else {
              $OSDeviceError.hide();
            }

            if (iOSVersionError || androidVersionError) {
              $OSVersionError.show();
            } else {
              $OSVersionError.hide();
            }
          }
        } else {
          $mobileOSHiddenInput.val('');
          $iOSDeviceHiddenInput.val('');
          $iOSVersionHiddenInput.val('');
          $androidDeviceHiddenInput.val('');
          $androidVersionHiddenInput.val('');
          $mobileOSGroup.hide();
          $OSDeviceGroup.hide();
        }

        if (priority.isHouse) {
            this.hide_budget()
            this.budgetValid = true;
        } else {
            this.show_budget()
            this.budgetValid = this.check_budget($form);
        }

        if(this.isAuction){
          this.showAuctionFields();
          this.setup_auction($form, targeting, timing);
          this.bidValid = this.check_bid_dollars($form);
        } else {
          this.bidValid = true;
          this.showCPMFields();
        }

        if (priority.isHouse && this.targetValid) {
            this.setup_house($form, targeting, timing, priority.isOverride);
        } else if (!this.isAuction && this.targetValid) {
            this.check_inventory($form, targeting, timing, budget, priority.isOverride)
        }
            
        if (targeting.canGeotarget) {
            this.enable_geotargeting();
        } else {
            this.disable_geotargeting();
        }

        var $frequencyCapped = $form.find('[name=frequency_capped]');
        if (this.frequency_capped === null) {
            this.frequency_capped = !!$frequencyCapped.val();
        }
        // In some cases, the frequency cap is automatically set, but no
        // frequencyCapped field is rendered; if so, skip this check
        if (this.frequency_capped && $frequencyCapped.length > 0) {
            var $frequencyCapField = $form.find('#frequency_cap'),
                frequencyCapValue = $frequencyCapField.val(),
                frequencyCapMin = $frequencyCapField.data('frequency_cap_min'),
                $frequencyCapError = $('.frequency-cap-field').find('.error');

            if (frequencyCapValue < frequencyCapMin || _.isNaN(parseInt(frequencyCapValue, 10))) {
                $frequencyCapError.show();
                isValidForm = false;
            } else {
                $frequencyCapError.hide();
            }
        }

        if(this.targetValid && this.budgetValid && this.bidValid){
          isValidForm = true;
        }

        if(isValidForm){ 
          this.enable_form($form);
        } else {
          if (!this.targetValid) {
            // target is not valid
            this.render_disabled_form("Please select a valid subreddit or collection");
          }
          this.disable_form($form);
        } 
        // If campaign is new, don't set up live editing fields
        if ($form.find('#is_new').val() === 'true') {
            this.setupLiveEditing(false);
        }

        var $noDailyBudget = $('[name="no_daily_budget"]');
        var $budgetDetails = $('.budget-details');

        $budgetDetails.toggle(!$noDailyBudget.is(':checked'));
    },

    render_disabled_form: function(msg){
      var $form = $("#campaign");
      if($form.length === 0){return;}
      var timing = this.get_timing($form);
      var budget = this.get_budget($form);

      React.renderComponent(
        CampaignSet(null,
          InfoText({className: 'error'},
            r._(msg)),
          CampaignOptionTable(null, CampaignOption({
            bidDollars: budget.cpm/100,
            totalBudgetDollars: budget.totalBudgetDollars,
            end: timing.enddate,
            impressions: budget.impressions,
            isNew: $form.find('#is_new').val() === 'true',
            primary: false,
            start: timing.startdate,
          }))
        ),
        document.getElementById('campaign-creator')
      );
    },

    disable_geotargeting: function() {
        $('.geotargeting-selects').find('select').prop('disabled', true).end().hide();
        $('.geotargeting-disabled').show();
    },

    enable_geotargeting: function() {
        $('.geotargeting-selects').find('select').prop('disabled', false).end().show();
        $('.geotargeting-disabled').hide();
    },

    disable_form: function($form) {
        $form.find('button[class*="campaign-button"]')
            .prop("disabled", true)
            .addClass("disabled");
    },

    enable_form: function($form) {

        $form.find('button[class*="campaign-button"]')
            .prop("disabled", false)
            .removeClass("disabled");
    },

    hide_budget: function() {
        $('.budget-field').css('display', 'none');
    },

    show_budget: function() {
        $('.budget-field').css('display', 'block');
    },

    subreddit_targeting: function() {
        $('.subreddit-targeting').find('*[name="sr"]').prop("disabled", false).end().slideDown();
        $('.collection-targeting').find('*[name="collection"]').prop("disabled", true).end().slideUp();
        this.render()
    },

    collection_targeting: function() {
        $('.subreddit-targeting').find('*[name="sr"]').prop("disabled", true).end().slideUp();
        $('.collection-targeting').find('*[name="collection"]').prop("disabled",  false).end().slideDown();
        this.render()
    },

    priority_changed: function() {
        this.render()
    },

    update_regions: function() {
        var $country = $('#country'),
            $region = $('#region'),
            $metro = $('#metro')

        $region.find('option').remove().end().hide()
        $metro.find('option').remove().end().hide()
        $region.prop('disabled', true)
        $metro.prop('disabled', true)

        if (_.has(this.regions, $country.val())) {
            _.each(this.regions[$country.val()], function(item) {
                var code = item[0],
                    name = item[1],
                    selected = item[2]

                $('<option/>', {value: code, selected: selected}).text(name).appendTo($region)
            })
            $region.prop('disabled', false)
            $region.show()
        }
    },

    update_metros: function() {
        var $region = $('#region'),
            $metro = $('#metro')

        $metro.find('option').remove().end().hide()
        if (_.has(this.metros, $region.val())) {
            _.each(this.metros[$region.val()], function(item) {
                var code = item[0],
                    name = item[1],
                    selected = item[2]

                $('<option/>', {value: code, selected: selected}).text(name).appendTo($metro)
            })
            $metro.prop('disabled', false)
            $metro.show()
        }
    },

    country_changed: function() {
        this.update_regions()
        this.render()
    },

    region_changed: function() {
        this.update_metros()
        this.render()
    },

    metro_changed: function() {
        this.render()
    },

    get_min_cpm_bid_dollars: function() {
        return parseFloat($('#bid_dollars').data('min_cpm_bid_dollars'));
    },

    get_max_cpm_bid_dollars: function() {
        return parseFloat($('#bid_dollars').data('max_cpm_bid_dollars'));
    },

    get_min_cpc_bid_dollars: function() {
        return parseFloat($('#bid_dollars').data('min_cpc_bid_dollars'));
    },

    get_max_cpc_bid_dollars: function() {
        return parseFloat($('#bid_dollars').data('max_cpc_bid_dollars'));
    },

    get_bid_dollars: function() {
        return parseFloat($('#bid_dollars').val());
    },

    get_lowest_max_cpm_bid_dollars: function($form) {
      var totalBudgetDollars = $form.find('#total_budget_dollars').val(),
          duration = this.get_timing($form).duration;

        // maxCpmBidDollars should be the lowest either
        // of maxCpmBidDollars or dailyMaxCpmBid
        var maxCpmBidDollars = r.sponsored.get_max_cpm_bid_dollars(),
            dailyMaxCpmBid = totalBudgetDollars / duration; 

        return Math.min(maxCpmBidDollars, dailyMaxCpmBid);
    },

    get_min_budget_dollars: function() {
        return $('#total_budget_dollars').data('min_budget_dollars');
    },

    get_max_budget_dollars: function() {
        return $('#total_budget_dollars').data('max_budget_dollars');
    },

    /**
    Checks budget 

    @returns {Boolean}
    */
    check_budget: function($form) {
        var budget = this.get_budget($form),
            minBudgetDollars = this.get_min_budget_dollars(),
            maxBudgetDollars = this.get_max_budget_dollars(),
            campaignName = $form.find('*[name=campaign_name]').val()

        $('.budget-change-warning').hide()
        if (campaignName != '') {
            var $campaignRow = $('.' + campaignName),
                campaignIsPaid = $campaignRow.data('paid'),
                campaignTotalBudgetDollars = $campaignRow.data('total_budget_dollars')
            if (campaignIsPaid && budget.totalBudgetDollars != campaignTotalBudgetDollars) {
                $('.budget-change-warning').show()
            }
        }

        $(".minimum-spend").removeClass("error");

        if (!this.userIsSponsor) {
            if (budget.totalBudgetDollars < minBudgetDollars) {
                this.budgetValid = false;
                $(".minimum-spend").addClass("error");
            } else if (budget.totalBudgetDollars > maxBudgetDollars) {
                this.budgetValid = false;
            } else {
                this.budgetValid = true;
                $(".minimum-spend").removeClass("error");
            }
        } else {
            this.budgetValid = true;
            $(".minimum-spend").removeClass("error");
        }

        return this.budgetValid;
    },

    /*
    Checks if bid dollars are valid

    @returns true if so, else false
    */
    check_bid_dollars: function($form) {
      var minBidDollars;
      var maxBidDollars;
      var bidDollars = r.sponsored.get_bid_dollars();
      var costBasis = $form.find('#cost_basis').val();

      if (costBasis === 'cpm') {
          minBidDollars = r.sponsored.get_min_cpm_bid_dollars();
          maxBidDollars = r.sponsored.get_lowest_max_cpm_bid_dollars($form);
          $form.find('.daily-max-spend').text(maxBidDollars.toFixed(2));
      } else if (costBasis === 'cpc') {
          minBidDollars = r.sponsored.get_min_cpc_bid_dollars();
          maxBidDollars = r.sponsored.get_max_cpc_bid_dollars();
      }

      // Form validation
      if (isNaN(maxBidDollars) || 
          isNaN(minBidDollars) || 
          isNaN(bidDollars)) {
          return false;
      } else {
          if (!this.userIsSponsor &&
              ((maxBidDollars < minBidDollars) ||
              (bidDollars < minBidDollars) ||
              (bidDollars > maxBidDollars))) {
            return false;
          }
          return true;
      }

    },

    calc_impressions: function(bid, cpm_pennies) {
        return Math.floor(bid / cpm_pennies * 1000 * 100);
    },

    calc_budget_dollars_from_impressions: function(impressions, cpm_pennies) {
        return (Math.floor(impressions * cpm_pennies / 1000) / 100).toFixed(2)
    },

    render_timing_duration: function($form, ndays) {
        var totalBudgetDollars = ndays + ' ' + ((ndays > 1) ? r._('days') : r._('day'));
        $form.find('.timing-field .duration').text(totalBudgetDollars);
    },

    fill_inventory_form: function() {
        var $form = $('.inventory-dashboard'),
            targeting = this.get_targeting($form),
            timing = this.get_timing($form);

        this.render_timing_duration($form, timing.duration);
    },

    submit_inventory_form: function() {
        var $form = $('.inventory-dashboard'),
            targeting = this.get_targeting($form),
            timing = this.get_timing($form);

        var data = {
            startdate: timing.startdate,
            enddate: timing.enddate,
        };

        if (targeting.type === 'collection') {
            data.collection_name = targeting.collection;
        }
        else if (targeting.type === 'subreddit') {
            data.sr_names = targeting.sr.join(',');
        }

        this.reload_with_params(data);
    },

    fill_reporting_form: function() {
        var $form = $('.reporting-dashboard'),
            timing = this.get_timing($form);

        this.render_timing_duration($form, timing.duration);
    },

    submit_reporting_form: function() {
        var $form = $('.reporting-dashboard'),
            timing = this.get_timing($form),
            reporting = this.get_reporting($form),
            grouping = $form.find("[name='grouping']").val();

        var data = {
            startdate: timing.startdate,
            enddate: timing.enddate,
            link_text: reporting.link_text,
            owner: reporting.owner,
            grouping: grouping,
        };

        this.reload_with_params(data);
    },

    reload_with_params: function(data) {
        var queryString = '?' + $.param(data);
        var location = window.location;
        window.location = location.origin + location.pathname + queryString;
    },

    mediaInputChange: function() {
        var $scraperInputWrapper = $('#scraper_input');
        var $rgInputWrapper = $('#rg_input');
        var isScraper = $(this).val() === 'scrape';

        $scraperInputWrapper.toggle(isScraper);
        $scraperInputWrapper.find('input').prop('disabled', !isScraper);
        $rgInputWrapper.toggle(!isScraper);
        $rgInputWrapper.find('input').prop('disabled', isScraper);
    },
};

}(r);

var dateFromInput = function(selector, offset) {
   if(selector) {
     var input = $(selector);
     if(input.length) {
        var d = new Date();
        offset = $.with_default(offset, 0);
        d.setTime(Date.parse(input.val()) + offset);
        return d;
     }
   }
};

function attach_calendar(where, min_date_src, max_date_src, callback, min_date_offset) {
     $(where).siblings(".datepicker").mousedown(function() {
            $(this).addClass("clicked active");
         }).click(function() {
            $(this).removeClass("clicked")
               .not(".selected").siblings("input").focus().end()
               .removeClass("selected");
         }).end()
         .focus(function() {
          var target = $(this);
          var dp = $(this).siblings(".datepicker");
          if (dp.children().length == 0) {
             dp.each(function() {
               $(this).datepicker(
                  {
                      defaultDate: dateFromInput(target),
                          minDate: dateFromInput(min_date_src, min_date_offset),
                          maxDate: dateFromInput(max_date_src),
                          prevText: "&laquo;", nextText: "&raquo;",
                          altField: "#" + target.attr("id"),
                          onSelect: function() {
                              $(dp).addClass("selected").removeClass("clicked");
                              $(target).blur();
                              if(callback) callback(this);
                          }
                })
              })
              .addClass("drop-choices");
          };
          dp.addClass("inuse active");
     }).blur(function() {
        $(this).siblings(".datepicker").not(".clicked").removeClass("inuse");
     }).click(function() {
        $(this).siblings(".datepicker.inuse").addClass("active");
     });
}

function sum(a, b) {
    // for things like _.reduce(list, sum);
    return a + b;
}

function check_enddate(startdate, enddate) {
  var startdate = $(startdate)
  var enddate = $(enddate);
  if(dateFromInput(startdate) >= dateFromInput(enddate)) {
    var newd = new Date();
    newd.setTime(startdate.datepicker('getDate').getTime() + 86400*1000);
    enddate.val((newd.getMonth()+1) + "/" +
      newd.getDate() + "/" + newd.getFullYear());
  }
  $("#datepicker-" + enddate.attr("id")).datepicker("destroy");
}

function extract_subreddits_from_str(str) {
  if(str.substring(0,3) !== "/r/"){
    // means this is a collection and not a list of subreddits
    return []
  }
  var srs = str.split(" ");
  //remove the "/r/" in from of the subreddits
  srs = srs.map(function(s){return s.substring(3)});
  return srs;
}

(function($) {
    $.update_campaign = function(campaign_name, campaign_html) {
        cancel_edit(function() {
            var $existing = $('.existing-campaigns .' + campaign_name),
                tableWasEmpty = $('.existing-campaigns table tr.campaign-row').length == 0

            if ($existing.length) {
                $existing.replaceWith(campaign_html)
                $existing.fadeIn()
            } else {
                $(campaign_html).hide()
                .appendTo('.existing-campaigns tbody')
                .css('display', 'table-row')
                .fadeIn()
            }

            if (tableWasEmpty) {
                $('.existing-campaigns p.error').hide()
                $('.existing-campaigns table').fadeIn()
                $('#campaign .buttons button[name=cancel]').removeClass('hidden')
                $("button.new-campaign").prop("disabled", false);
            }

            r.sponsored.render_campaign_dashboard_header();
        })
    }
}(jQuery));

function detach_campaign_form() {
    /* remove datepicker from fields */
    $("#campaign").find(".datepicker").each(function() {
            $(this).datepicker("destroy").siblings().unbind();
        });

    /* detach and return */
    var campaign = $("#campaign").detach();
    return campaign;
}

function cancel_edit(callback) {
    var $campaign = $('#campaign');
    var isEditingExistingCampaign = !!$campaign.parents('tr:first').length;

    if (isEditingExistingCampaign) {
        var tr = $campaign.parents("tr:first").prev();
        /* copy the campaign element */
        /* delete the original */
        $campaign.slideUp(function() {
                $(this).parent('tr').prev().fadeIn();
                var td = $(this).parent();
                var campaign = detach_campaign_form();
                td.delete_table_row(function() {
                        tr.fadeIn(function() {
                                $('.new-campaign-container').append(campaign);
                                campaign.hide();
                                if (callback) { callback(); }
                            });
                    });
            });
        r.srAutocomplete.srReset(); // resets the subreddit autocomplete
    } else {
        var keep_open = $campaign.hasClass('keep-open');
        
        if ($campaign.is(':visible') && !keep_open) {
            $campaign.slideUp(callback);
        } else if (callback) {
            callback();
        }

        if (keep_open) {
            $campaign.removeClass('keep-open');
            $campaign.find('.status')
                .text(r._('Created new campaign!'))
                .show()
                .delay(1000)
                .fadeOut();

            r.sponsored.render();
        } else {
            r.srAutocomplete.srReset(); // resets the subreddit autocomplete
        }
    }
}

function send_campaign(close) {
    if (!close) {
        $('#campaign').addClass('keep-open');
    }

    post_pseudo_form('.campaign', 'edit_campaign');
}

function del_campaign($campaign_row) {
    var link_id36 = $("#campaign").find('*[name="link_id36"]').val(),
        campaign_id36 = $campaign_row.data('campaign_id36')
    $.request("delete_campaign", {"campaign_id36": campaign_id36,
                                  "link_id36": link_id36},
              null, true, "json", false);
    $campaign_row.children(":first").delete_table_row(function() {
        r.sponsored.render_campaign_dashboard_header();
        return check_number_of_campaigns();
    });
}

function toggle_pause_campaign($campaign_row, shouldPause) {
    var link_id36 = $('#campaign').find('*[name="link_id36"]').val(),
        campaign_id36 = $campaign_row.data('campaign_id36')
    $.request('toggle_pause_campaign', {'campaign_id36': campaign_id36,
                                        'link_id36': link_id36,
                                        'should_pause': shouldPause},
              null, true, 'json', false);
    r.sponsored.render();
}

function edit_campaign($campaign_row) {
    cancel_edit(function() {
        cancel_edit_promotion();
        var campaign = detach_campaign_form(),
            campaignTable = $(".existing-campaigns table").get(0),
            editRowIndex = $campaign_row.get(0).rowIndex + 1
            $editRow = $(campaignTable.insertRow(editRowIndex)),
            $editCell = $("<td>").attr("colspan", r.sponsored.campaignListColumns).append(campaign)

        $editRow.attr("id", "edit-campaign-tr")
        $editRow.append($editCell)
        $campaign_row.fadeOut(function() {
            /* fill inputs from data in campaign row */
            _.each(['startdate', 'enddate', 'bid', 'campaign_id36', 'campaign_name',
                    'frequency_cap', 'total_budget_dollars',
                    'bid_dollars', 'no_daily_budget', 'auto_extend'],
                function(input) {
                    var val = $campaign_row.data(input),
                        $input = campaign.find('*[name="' + input + '"]');

                    switch ($input.attr('type')) {
                      case 'checkbox':
                        $input.prop('checked', val === 'True');
                        break;
                      default:
                        $input.val(val)
                    }
            })

            if ($campaign_row.data('is_auction') === 'True') {
              r.sponsored.isAuction = true;
            } else {
              r.sponsored.isAuction = false;
            }

            var autoExtending = $campaign_row.data('is_auto_extending') == 'True';

            if (autoExtending) {
              var originalEnd = $campaign_row.data('pre_extension_end_date');
              var extensionsRemaining = $campaign_row.data('extensions_remaining');

              $('[name=no_daily_budget]')
                .prop('checked', true)
                .attr('disabled', 'disabled');

              $('[name=auto_extend]')
                .closest('label')
                .append(
                  $('<span class="auto-extend-status"></span>')
                    .text(' (original end: ' + originalEnd +
                    ', days left: ' + extensionsRemaining + ')')
                );
            } else {
              $('[name=no_daily_budget]').removeAttr('disabled');
              $('.auto-extend-status').remove();
            }

            var platform = $campaign_row.data('platform');
            campaign.find('*[name="platform"][value="' + platform + '"]').prop("checked", "checked");

            /* set mobile targeting */
            r.sponsored.setup_mobile_targeting(
              $campaign_row.data('mobile_os'),
              $campaign_row.data('ios_devices'),
              $campaign_row.data('ios_versions'),
              $campaign_row.data('android_devices'),
              $campaign_row.data('android_versions')
            );

            /* pre-select mobile OS checkboxes if current platform is not mobile */
            campaign.find('.mobile-os-group input').prop("checked", !r.sponsored.mobileOS);

            /* logic if filtering by device and OS */
            if (r.sponsored.iOSDevices || r.sponsored.androidDevices) {
              /* pre-select the device and OS version radio button */
              campaign.find('#filter_os_devices').prop('checked', 'checked');

              /* first, clear all checked devices (they're checked by default),
                 but only if the campaign has devices for the OS */
              if (r.sponsored.iOSDevices) {
                campaign.find('.ios-device input[type="checkbox"]').prop('checked', false);
              }
              if (r.sponsored.androidDevices) {
                campaign.find('.android-device input[type="checkbox"]').prop('checked', false);
              }

              /* then, pre-select all appropriate devices */
              var allDevices = [].concat(r.sponsored.iOSDevices, r.sponsored.androidDevices);
              allDevices.forEach(function(device) {
                if (device) {
                  campaign.find('#'+device.toLowerCase()).prop('checked', true);
                }
              });

              /* pre-select iOS versions */
              if (r.sponsored.iOSVersions) {
                campaign.find('#ios_min').val(r.sponsored.iOSVersions[0]);
                campaign.find('#ios_max').val(r.sponsored.iOSVersions[1]);
              }

              /* pre-select Android versions */
              if (r.sponsored.androidVersions) {
                campaign.find('#android_min').val(r.sponsored.androidVersions[0]);
                campaign.find('#android_max').val(r.sponsored.androidVersions[1]);
              }
            } else {
              campaign.find('#all_os_devices').prop('checked', true);
            }

            var mobile_os_names = $campaign_row.data('mobile_os');
            if (mobile_os_names) {
              mobile_os_names.forEach(function(name) {
                campaign.find('#mobile_os_' + name).prop("checked", "checked");
              });
            }

            r.sponsored.setup_frequency_cap($campaign_row.data('frequency_cap'));
            /* show frequency inputs */
            if ($campaign_row.data('frequency_cap')) {
              $('.frequency-cap-field').show();
              $('#frequency_capped_true').prop('checked', 'checked');
            }

            /* set priority */
            var priorities = campaign.find('*[name="priority"]'),
                campPriority = $campaign_row.data("priority")

            priorities.filter('*[value="' + campPriority + '"]')
                .prop("checked", "checked")

            /* check if targeting is turned on */
            var targeting = $campaign_row.data("targeting"),
                radios = campaign.find('*[name="targeting"]'),
                isCollection = ($campaign_row.data("targeting-collection") === "True"),
                collectionTargeting = isCollection ? targeting : 'none';

            // functions to support multisubreddit handling
            if (targeting && !isCollection) {
                radios.filter('*[value="subreddit"]')
                    .prop("checked", "checked");
                r.srAutocomplete.srAddSr(targeting);
                campaign.find('*[name="sr"]').prop("disabled", false).end()
                    .find(".subreddit-targeting").show();
                $(".collection-targeting").hide();
            } else {
                var srs = extract_subreddits_from_str(targeting);
                if(srs.length > 0){
                  // Multisubreddits
                  radios.filter('*[value="subreddit"]')
                    .prop("checked", "checked");
                  srs.forEach(r.srAutocomplete.srAddSr(
                    undefined,
                    {
                      noNewSuggestions: true,
                    }
                  ));
                  campaign.find('*[name="sr"]').prop("disabled", false).end()
                      .find(".subreddit-targeting").show();
                  $(".collection-targeting").hide();
                } else {
                  // Plain old collection
                  radios.filter('*[value="collection"]')
                      .prop("checked", "checked");
                  $('.collection-targeting input[value="' + collectionTargeting + '"]')
                      .prop("checked", "checked");
                  campaign.find('*[name="sr"]').val("").prop("disabled", true).end()
                      .find(".subreddit-targeting").hide();
                  $('.collection-targeting').show();
                }
            }

            r.sponsored.collapse_collection_selector();

            /* set geotargeting */
            var country = $campaign_row.data("country"),
                region = $campaign_row.data("region"),
                metro = $campaign_row.data("metro")
            campaign.find("#country").val(country)
            r.sponsored.update_regions()
            if (region != "") {
                campaign.find("#region").val(region)
                r.sponsored.update_metros()

                if (metro != "") {
                    campaign.find("#metro").val(metro)
                }
            }

            /* set cost basis */
            $('#cost_basis').val($campaign_row.data('cost_basis'));

            /* attach the dates to the date widgets */
            init_startdate();
            init_enddate();

            /* setup fields for live campaign editing */
            r.sponsored.setupLiveEditing($campaign_row.data('is_live') === 'True');

            campaign.find('#is_new').val('false')

            campaign.find('button[name="save"]').show().end()
                .find('.create').hide().end();
            campaign.slideDown();
            r.sponsored.render();
        })
    })
}

function check_number_of_campaigns(){
    if ($(".campaign-row").length >= $(".existing-campaigns").data("max-campaigns")){
      $(".error.TOO_MANY_CAMPAIGNS").fadeIn();
      $("button.new-campaign").prop("disabled", true);
      return true;
    } else {
      $(".error.TOO_MANY_CAMPAIGNS").fadeOut();
      $("button.new-campaign").prop("disabled", false);
      return false;
    }
}

function create_campaign() {
    if (check_number_of_campaigns()){
        return;
    }

    var link_id36 = $("#campaign").find('*[name="link_id36"]').val();

    r.analytics.fireFunnelEvent('ads', 'new-campaign');
    r.analytics.adsInteractionEvent('new_campaign', {
      link_id: parseInt(link_id36, 36),
    });

    cancel_edit(function() {
            cancel_edit_promotion();
            var defaultBudgetDollars = $("#total_budget_dollars").data("default_budget_dollars");

            init_startdate();
            init_enddate();

            $('#campaign')
                .find(".collection-targeting").show().end()
                .find('input[name="collection"]').prop("disabled", false).end()
                .find('input[name="collection"]').eq(0).prop("checked", "checked").end().end()
                .find('input[name="collection"]').slice(1).prop("checked", false).end().end()
                .find('.collection-selector .form-group-list').css('top', 0).end()
            r.sponsored.collapse_collection_selector();

            $("#campaign")
                .find('button[name="save"]').hide().end()
                .find('.create').show().end()
                .find('input[name="campaign_id36"]').val('').end()
                .find('input[name="campaign_name"]').val('').end()
                .find('input[name="sr"]').val('').prop("disabled", true).end()
                .find('input[name="targeting"][value="collection"]').prop("checked", "checked").end()
                .find('input[name="priority"][data-default="true"]').prop("checked", "checked").end()
                .find('input[name="total_budget_dollars"]').val(defaultBudgetDollars).end()
                .find(".subreddit-targeting").hide().end()
                .find('select[name="country"]').val('').end()
                .find('select[name="region"]').hide().end()
                .find('select[name="metro"]').hide().end()
                .find('input[name="frequency_cap"]').val('').end()
                .find('input[name="startdate"]').prop('disabled', false).end()
                .find('#frequency_capped_false').prop('checked', 'checked').end()
                .find('.frequency-cap-field').hide().end()
                .find('input[name="is_new"]').val('true').end()
                .find('input[name="auto_extend"]').prop('checked', true).end()
                .slideDown();
            r.sponsored.render();
        });
}

function free_campaign($campaign_row) {
    var link_id36 = $("#campaign").find('*[name="link_id36"]').val(),
        campaign_id36 = $campaign_row.data('campaign_id36')
    $.request("freebie", {"campaign_id36": campaign_id36, "link_id36": link_id36},
              null, true, "json", false);
    $campaign_row.find(".free").fadeOut();
    return false; 
}

function terminate_campaign($campaign_row) {
    var link_id36 = $("#campaign").find('*[name="link_id36"]').val(),
        campaign_id36 = $campaign_row.data('campaign_id36')
    $.request("terminate_campaign", {"campaign_id36": campaign_id36,
                                     "link_id36": link_id36},
              null, true, "json", false);
}

function open_reject_campaign($campaign_row) {
  $campaign_row.find('button.reject').hide();
  $campaign_row.find('.campaign-rejection-form').show().find('textarea').focus();
}

function cancel_reject_campaign($campaign_row) {
  $campaign_row.find('button.reject').show();
  $campaign_row.find('.campaign-rejection-form').hide();
}

function approve_campaign($campaign_row, approved) {
  var campaignId = $campaign_row.data('campaign_id36');
  var linkId = $campaign_row.data('link_id36');
  var $hideAfter = $campaign_row.find('input[name="hide_after"]');
  var hideAfter = false;
  var reason = '';

  if ($hideAfter.length) {
    hideAfter = $hideAfter.val();
  }

  if (!approved) {
    $rejectionForm = $campaign_row.find('.campaign-rejection-form');
    reason = $rejectionForm.find('textarea').val();
  }

  $.request('approve_campaign', {
    campaign_id36: campaignId,
    link_id36: linkId,
    hide_after: hideAfter,
    approved: approved,
    reason: reason,
  }, null, true, 'json', false);
}

function edit_promotion() {
    $("button.new-campaign").prop("disabled", false);
    cancel_edit(function() {
        $('.promotelink-editor')
            .find('.collapsed-display').slideUp().end()
            .find('.uncollapsed-display').slideDown().end()
    })
    return false;
}

function cancel_edit_promotion() {
    $('.promotelink-editor')
        .find('.collapsed-display').slideDown().end()
        .find('.uncollapsed-display').slideUp().end()

    return false;
}

function cancel_edit_campaign() {
    $("button.new-campaign").prop("disabled", false);
    return cancel_edit()
}

!function(exports) {
    /*
     * @param {number[]} days An array of inventory for the campaign's timing
     * @param {number} minValidRequest The minimum request a campaign is allowed
     *                                 to have, should be in the same units as `days`
     * @param {number} requested The campaign's requested inventory, in the same
     *                           units as `days` and `minValidRequest`.
     * @param {number} maxOffset maximum valid start index
     * @returns {{days: number[], maxRequest: number, offset:number}|null}
     *                            The sub-array, maximum request for it, and
     *                            its offset from the original `days` array.
     */
    exports.getMaximumRequest = _.memoize(
      function getMaximumRequest(days, minValidRequest, requested, maxOffset) {
        return check(days, 0);

        /**
         * check if a set of days is valid, then compare to results of this 
         * function called on subsets of that date range
         * @param  {Number[]} days inventory values
         * @param  {Number} offset offset from the original days array we are
         *                         working on
         * @return {Object|null}  object describing the best range found,
         *                        or null if no valid range was found
         */
        function check(days, offset) {
          var bestOption = null;
          if (days.length > 0 && offset <= maxOffset) {
            // check the validity of the days array.
            var minValue = min(days);
            var maxRequest = minValue * days.length;
            if (maxRequest >= minValidRequest) {
              bestOption = {days: days, maxRequest: maxRequest, offset: offset};
            }
          }
          if (bestOption === null || bestOption.maxRequest < requested) {
            // if bestOptions does not hit our target, check sub-arrays.  start
            // by splitting on values that invalidate the date range (anything
            // with inventory below the minimum daily amount).
            // subtract 0.1 because the comparison used to filter is > (not >=)
            var minDaily = days.length / minValidRequest - 0.1;
            return split(days, offset, bestOption, minDaily, check, true)
          }
          else {
            return bestOption;
          }
        }
      },
      function hashFunction(days, minValidRequest, requested) {
        return [days.join(','), minValidRequest, requested].join('|');
      }
    );

    /**
     * compare two date range options, returning the better
     * options are compared on their maximum request first, then their duration
     * @param  {Object|null} a
     * @param  {Object|null} b
     * @return {Object|null}
     */
    function compare(a, b) {
      if (!b) {
        return a;
      }
      else if (!a) {
        return b;
      }
      if (b.maxRequest > a.maxRequest ||
          (b.maxRequest === a.maxRequest && b.days.length > a.days.length)) {
        return b;
      }
      else {
        return a;
      }
    }

    function min(arr) {
      return Math.min.apply(Math, arr);
    }

    /**
     * split an array of inventory into sub-arrays, checking each
     * @param  {number[]} days - inventory data for a range of contiguous dates
     * @param  {number} offset - index offset from original array
     * @param  {Object|null} bestOption - current best option
     * @param  {number} minValue - value used to split the days array on; values
     *                             below this are excluded
     * @param  {function} check - function to call on sub-arrays
     * @param  {boolean} recurse - whether or not to call this function again if
     *                             unable to split array (more on this below)
     * @return {Object|null} - best option found
     */
    function split(days, offset, bestOption, minValue, check, recurse) {
      var sub = [];
      var subOffset = 0;
      for (var i = 0, l = days.length; i < l; i++) {
        if (days[i] > minValue) {
          if (sub.length === 0) {
            subOffset = offset + i;
          }
          sub.push(days[i])
        }
        else {
          // whenever we hit the end of a contiguous set of days above the 
          // minValue threshold, compare that sub-array to our current bestOption
          if (sub.length) {
            bestOption = compare(bestOption, check(sub, subOffset))
            sub = [];
          }
        }
      }
      if (sub.length === days.length) {
        // if the array was not split at all:
        if (recurse) {
          // if we were previously splitting on the minimum valid value, try
          // splitting on the smallest value in the array.  The `recurse` value
          // prevents this from looping infinitely
          return compare(bestOption, split(days, offset, null, min(days), check, false));
        }
        else {
          // otherwise, just return the current best
          return bestOption;
        }
      }
      else if (sub.length) {
        // need to compare the last sub array, as it won't checked in the for loop
        return compare(bestOption, check(sub, subOffset));
      }
      else {
        // if _no_ values were found above the minValue threshold
        return bestOption;
      }
    }
}(r.sponsored);
