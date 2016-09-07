!function(r) {
  if (!r.config.logged) { return }

  r.onboarding = {
    init: function() {
      var content = $('#' + 'onboarding-popup').html();
      var onboardingPopup = new r.ui.Popup({
        size: 'xlarge',
        content: content,
        className: 'onboarding',
        backdrop: 'static',
      });

      // Update the header on the confirmation modal to include username.
      var $congratsLine = onboardingPopup.$.find('.onboarding__username');
      $congratsLine.text($congratsLine.text().format({name: r.config.logged}));

      var MIN_VALID_SELECTIONS = 3;

      var didUpdateSubscriptions = false;
      var shouldShowConfirmationModal = false;
      var isValidSelection = true;

      // Randomly select a set of 3 categories to enable by default.
      var checkboxes = onboardingPopup.$.find('.onboarding__checkbox-input').toArray();
      var checkboxesToAutoCheck = _.shuffle(checkboxes).slice(0, MIN_VALID_SELECTIONS);
      checkboxesToAutoCheck.forEach(function (el) {
        $(el).prop('checked', true);
      });

      // Any time a checkbox changes, validate and update the submit button.
      onboardingPopup.$.on('change', '.onboarding__checkbox-input', function() {
        var countOfCheckedCheckboxes = 0;
        for (var i = 0; i < checkboxes.length; i++) {
          if ($(checkboxes[i]).prop('checked')) {
            countOfCheckedCheckboxes++;
            if (countOfCheckedCheckboxes >= MIN_VALID_SELECTIONS) {
              isValidSelection = true;
              onboardingPopup.$.find('.onboarding__action--submit').prop('disabled', false);
              return;
            }
          }
        }
        onboardingPopup.$.find('.onboarding__action--submit').prop('disabled', true);
        isValidSelection = false;
      });

      // Any time the modal closes, check what needs to happen next (if anything).
      onboardingPopup.on('closed.r.popup', function() {
        if (shouldShowConfirmationModal) {
          shouldShowConfirmationModal = false;
          onboardingPopup.$.find('.onboarding__step--choose-categories').hide();
          onboardingPopup.$.find('.onboarding__step--complete').show();
          onboardingPopup.show();
        } else if (didUpdateSubscriptions) {
          window.location.reload();
        }
      });

      // When the submit button is clicked, make the API request then close the modal.
      onboardingPopup.$.on('click', '.onboarding__action--submit', function(e) {
        if (!isValidSelection) { return }

        var subreddits = getSubredditsFromSelectedCategories(onboardingPopup);

        // TODO - what should we do if _nothing_ is selected? use defaults?
        // should we allow people to subscribe to _nothing_??

        subscribeToSubreddits(
          subreddits,
          function onSucces() {
            didUpdateSubscriptions = true;
            shouldShowConfirmationModal = true;
            onboardingPopup.hide();
          },
          function onError() {
            onboardingPopup.hide();
          }
        );

        return false;
      });

      // When the "use defaults" button is clicked, just go to the confirmation page.
      onboardingPopup.$.on('click', '.onboarding__action--default', function(e) {
        shouldShowConfirmationModal = true;
        onboardingPopup.hide();
        return false;
      });

      // When one of the close buttons is clicked, close the modal and do nothing.
      onboardingPopup.$.on('click', '.onboarding__action--close', function(e) {
        onboardingPopup.hide();
        return false;
      });

      onboardingPopup.show();
    },
  };

  $(function() {
    r.onboarding.init();
  });

  function getCategoryDataFromElement (element) {
    var $el = $(element);
    var subredditNames = $el.data('sr-names').split(',');
    var $input = $el.find('.onboarding__checkbox-input');
    var multiName = $input.attr('name');
    var checked = $input.is(':checked');

    return {
      name: multiName,
      active: checked,
      subreddits: subredditNames,
    };
  }

  function getSubredditsFromSelectedCategories (onboardingPopup) {
    var activeSubredditsMap = {};
    var $categories = onboardingPopup.$.find('.onboarding__category');
    var categoryElements = $categories.toArray();

    categoryElements.forEach(function(element) {
      var categoryData = getCategoryDataFromElement(element);

      if (categoryData.active) {
        for (var i = 0; i < categoryData.subreddits.length; i++) {
          activeSubredditsMap[categoryData.subreddits[i]] = 1;
        }
      }
    });

    return Object.keys(activeSubredditsMap);
  }

  function subscribeToSubreddits(subreddits, onSuccess, onError) {
    r.ajax({
      type: 'POST',
      url: '/api/subscribe',
      data: {
        sr: subreddits.join(','),
        action: 'sub',
        skip_initial_defaults: true,
      },
      success: onSuccess,
      error: onError,
    });
  }
}(r);
