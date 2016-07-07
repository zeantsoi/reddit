r.promoted = {

  init: function() {
    this.addExpandTargetingLinks();
  },

  addExpandTargetingLinks: function() {
    $('.toggle-campaign-target').each(function(index, element) {
      var $campaignRow = $(element).closest('.campaign-row');
      var $expandLink = this.getTargetingExpandLink($campaignRow);
      $(element).html($expandLink);
    }.bind(this));
  },

  getTargetingExpandLink: function($campaignRow) {
    var text = r._('show all %(rows)s').format({rows: $campaignRow.data('full-target-count')})
    return $('<a />').on('click',
                         r.promoted.addExpandTargetingLink.bind(this, $campaignRow))
                     .css('cursor', 'pointer')
                     .text(text);
  },

  getTargetingCollapseLink: function($campaignRow) {
    var text = r._('show less');
    return $('<a />').on('click',
                         r.promoted.addCollapseTargetingLink.bind(this, $campaignRow))
                     .css('cursor', 'pointer')
                     .text(text);
  },

  addExpandTargetingLink: function($campaignRow) {
    var targetingString = $campaignRow.data('targeting');
    var $collapseLink = this.getTargetingCollapseLink($campaignRow);
    var $targetingDiv = $campaignRow.find('.campaign-target');
    $targetingDiv.text(targetingString).append($collapseLink);
  },

  addCollapseTargetingLink: function($campaignRow) {
    var truncatedTargetingString = $campaignRow.data('truncated-targeting');
    var $expandLink = this.getTargetingExpandLink($campaignRow);
    var $targetingDiv = $campaignRow.find('.campaign-target');
    $targetingDiv.text(truncatedTargetingString).append($expandLink);
  },

};
