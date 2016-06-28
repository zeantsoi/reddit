!(function(r) {

  $('.topbar-menu').on('click', function(e) {
    var $el = $(this);
    $('.topbar-menu').each(function(index, el) {
      var $currentEl = $(el);
      if (!$el.is($currentEl)) {
        $currentEl.find('.topbar__dropdown').hide();
        $currentEl.find('.topbar__arrow-icon').removeClass('up');
      }
    })
    $el.find('.topbar__dropdown').toggle();
    $el.find('.topbar__arrow-icon').toggleClass('up');
  });

  $('#search input[type=submit]').on('click', function(e) {
    var $input = $('.search-input');
    if (!$input.is(":visible")) {
      e.preventDefault();
      $input.show();
      $input.focus();
    }
  });

  $(window).on('click', function(e) {
    var target = e.target;
    if (!$(target).parents(".topbar-menu").length == 1) {
      $('.topbar__dropdown').hide()
      $('.topbar__arrow-icon').removeClass('up');
    }
  })

})(r);
