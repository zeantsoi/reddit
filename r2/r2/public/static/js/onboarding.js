!function(r) {
  if (!r.config.logged) { return }

  r.onboarding = {
    init: function() {
      var content = $('#onboarding-popup').html();
      var onboardingPopup = new r.ui.Popup({
        size: 'xlarge',
        content: content,
        className: 'onboarding',
        backdrop: 'static',
      });

      // Update the header on the confirmation modal to include username.
      var $congratsLine = onboardingPopup.$.find('[ref=username]');
      $congratsLine.text($congratsLine.text().format({name: r.config.logged}));

      var MIN_VALID_SELECTIONS = 3;

      var isSubmitting = false;
      var didUpdateSubscriptions = false;
      var shouldShowConfirmationModal = false;
      var isValidSelection = true;

      // Randomly select a set of 3 categories to enable by default.
      var checkboxes = onboardingPopup.$.find('[ref=checkbox]').toArray();
      var checkboxesToAutoCheck = _.shuffle(checkboxes).slice(0, MIN_VALID_SELECTIONS);
      checkboxesToAutoCheck.forEach(function (el) {
        $(el).prop('checked', true);
      });

      var preselectedCategories = checkboxesToAutoCheck.map(function (el) {
        return $(el).attr('name');
      });
      r.actions.trigger('onboarding:preselect', {
        categories: preselectedCategories,
      });

      // Any time a checkbox changes, validate and update the submit button.
      onboardingPopup.$.on('change', '[ref=checkbox]', function() {
        var numChecked = onboardingPopup.$.find('[ref=checkbox]:checked').length;
        isValidSelection = (numChecked >= MIN_VALID_SELECTIONS);
        onboardingPopup.$.find('[ref=action--submit]').prop('disabled', !isValidSelection);
      });

      // Any time the modal closes, check what needs to happen next (if anything).
      onboardingPopup.on('closed.r.popup', function() {
        if (shouldShowConfirmationModal) {
          shouldShowConfirmationModal = false;
          onboardingPopup.$.find('[ref=step--choose-categories]').hide();
          onboardingPopup.$.find('[ref=step--complete]').show();
          onboardingPopup.show();
        } else if (didUpdateSubscriptions) {
          window.location.reload();
        }
      });

      // When the submit button is clicked, make the API request then close the modal.
      onboardingPopup.$.on('click', '[ref=action--submit]', function(e) {
        if (!isValidSelection || isSubmitting) { return }

        isSubmitting = true;
        onboardingPopup.$.find('[ref=action--submit]').prop('disabled', true);
        onboardingPopup.$.find('[ref=action--default]').prop('disabled', true);
        var categoryData = getSelectedCategoryData(onboardingPopup);
        var subreddits = getSubredditsFromCategoryData(categoryData);
        var categoryNames = categoryData.map(function(category) {
          return category.name;
        });

        subscribeToSubreddits(
          subreddits,
          function onSuccess() {
            didUpdateSubscriptions = true;
            shouldShowConfirmationModal = true;
            onboardingPopup.hide();
            r.actions.trigger('onboarding:submit', {
              selectedCategories: categoryNames, 
            });
          },
          function onError() {
            onboardingPopup.hide();
          }
        );

        return false;
      });

      // When the "use defaults" button is clicked, just go to the confirmation page.
      onboardingPopup.$.on('click', '[ref=action--default]', function(e) {
        if (isSubmitting) { return }

        r.actions.trigger('onboarding:default'); 
        shouldShowConfirmationModal = true;
        onboardingPopup.hide();
        return false;
      });

      // When one of the close buttons is clicked, close the modal and do nothing.
      onboardingPopup.$.on('click', '[ref=action--close]', function(e) {
        r.actions.trigger('onboarding:close', {
          skippedOnboarding: !didUpdateSubscriptions,
        });
        onboardingPopup.hide();
        return false;
      });

      onboardingPopup.show();
    },
  };

  $(function() {
    r.onboarding.init();
  });

  function getCategoryDataFromElement(element) {
    var $el = $(element);
    var subredditNames = $el.data('sr-names').split(',');
    var $input = $el.find('[ref=checkbox]');
    var multiName = $input.attr('name');
    var checked = $input.is(':checked');

    return {
      name: multiName,
      active: checked,
      subreddits: subredditNames,
    };
  }

  function getSelectedCategoryData(onboardingPopup) {
    var $categories = onboardingPopup.$.find('[ref=category]');
    var categoryElements = $categories.toArray();

    return categoryElements.map(function(element) {
      return getCategoryDataFromElement(element);
    }).filter(function(item) {
      return item.active;
    });
  }

  function getSubredditsFromCategoryData(categoryData) {
    var activeSubredditsMap = {};

    categoryData.forEach(function(category) {
      if (category.active) {
        for (var i = 0; i < category.subreddits.length; i++) {
          activeSubredditsMap[category.subreddits[i]] = 1;
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
