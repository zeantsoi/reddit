!function(r, undefined) {
  var RES_STORAGE_TEST_KEY = 'RES.localStorageTest';

  var PLUGIN_STATE_KEY = 'plugin.RES.state';
  var PLUGIN_STATE_MAYBE = 'MAYBE';
  var PLUGIN_STATE_ACTIVE = 'ACTIVE';
  var PLUGIN_STATE_INACTIVE = 'INACTIVE';

  /*
    Use two localStorage keys - one set by RES during initialization, one by
    us here - to determine whether or not RES is currently installed.  This
    relies on a couple of facts:

    1. RES always sets RES_STORAGE_TEST_KEY during its initialization.
    2. RES never removes RES_STORAGE_TEST_KEY.
    3. RES doesn't use RES_STORAGE_TEST_KEY in any other capacity.
    4. RES's localStorage test will *before* this.
   */
  function updateResLocalStorageState() {
    var state = localStorage.getItem(PLUGIN_STATE_KEY);
    var resTest = localStorage.getItem(RES_STORAGE_TEST_KEY);

    if (!state) {

      if (resTest) {
        // RES's localStorage test key exists, so it might be enabled.
        localStorage.setItem(PLUGIN_STATE_KEY, PLUGIN_STATE_MAYBE);
        // Remove it and see if it gets added back in on the next page load.
        localStorage.removeItem(RES_STORAGE_TEST_KEY);
      } else {
        // RES hasn't been enabled on this browser.
        localStorage.setItem(PLUGIN_STATE_KEY, PLUGIN_STATE_INACTIVE);
      }

    } else if (state === PLUGIN_STATE_MAYBE) {

      if (resTest) {
        // RES has added their localStorage test key back in; it's active.
        localStorage.setItem(PLUGIN_STATE_KEY, PLUGIN_STATE_ACTIVE);
        // Remove it again, so we can detect if it gets disabled.
        localStorage.removeItem(RES_STORAGE_TEST_KEY);
      } else {
        // RES must have been enabled in the past, but currently disabled.
        localStorage.setItem(PLUGIN_STATE_KEY, PLUGIN_STATE_INACTIVE);
      }

    } else if (state === PLUGIN_STATE_INACTIVE) {

      if (resTest) {
        // RES has been activated.
        localStorage.setItem(PLUGIN_STATE_KEY, PLUGIN_STATE_ACTIVE);
        // Remove the test key so we can track when it's disabled.
        localStorage.removeItem(RES_STORAGE_TEST_KEY);
      } else {
        // RES is still disabled; do nothing.
      }

    } else {

      if (resTest) {
        // RES is still active.  Remove their key again so we can detect disable.
        localStorage.removeItem(RES_STORAGE_TEST_KEY);
        // Always setting our key here will ensure it gets corrected if anyone
        // manually sets it to something unexpected
        localStorage.setItem(PLUGIN_STATE_KEY, PLUGIN_STATE_ACTIVE)
      } else {
        // RES has been disabled.
        localStorage.setItem(PLUGIN_STATE_KEY, PLUGIN_STATE_INACTIVE);
      }

    }
  }

  $(function() {
    // For this to work correctly, RES's initializtion needs to have already
    // run.  From testing, it seems that it's not actually necessary to wait
    // for domready, but better safe than sorry.
    try {
      updateResLocalStorageState();
    } catch (err) {
      // LocalStorage isn't available
    }
  });

  r.isResActive = function() {
    // If you need to know for sure that RES is definitely disabled, explicitly
    // check the return value == false.  This will return undefined in cases
    // where we can't be sure if RES is on or off.
    try {
      var state = localStorage.getItem(PLUGIN_STATE_KEY);

      if (state === PLUGIN_STATE_ACTIVE) {
        return true
      } else if (state === PLUGIN_STATE_INACTIVE) {
        return false;
      }
    } catch (err) {
      // LocalStorage isn't available
    }
  };
}(r);
