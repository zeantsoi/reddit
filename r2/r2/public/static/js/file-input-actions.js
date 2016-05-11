!function(r) {
  // https://developer.mozilla.org/en-US/docs/Web/API/DataTransfer
  // https://developer.mozilla.org/en-US/docs/Web/Guide/HTML/Drag_operations
  // https://developer.mozilla.org/en-US/docs/Web/API/File

  var ACTION_NAME = 'file-input';

  /**
   * Binds an image-upload action to the 'change' event of target file input
   * @param  {HTMLInputElement} target - should be a file input
   * @param  {HTMLElement|void} eventTarget - element to use as the target in
   *                                          the event (defaults to target)
   */
  r.actions.bindImageUploadOnInput = function(target, eventTarget) {
    eventTarget = eventTarget || target;
    $(target).on('change', function(e) {
      /** @type {File} */
      var file = e.originalEvent.target.files[0];
      if (!file) { return; }

      r.actions.trigger(ACTION_NAME, {
        target: eventTarget,
        eventDetail: 'input',
        file: file,
      });
    });
  }

  /**
   * Binds an image-upload action to the 'paste' event of target element
   * @param  {HTMLElement|Window} target - probably most useful if set to window
   * @param  {HTMLElement|void} eventTarget - element to use as the target in
   *                                          the event (defaults to target)
   */
  r.actions.bindImageUploadOnPaste = function(target, eventTarget) {
    eventTarget = eventTarget || target;
    $(target).on('paste', function(e) {
      /** @type {DataTransferItem|void} */ 
      var dataTransfer = e.originalEvent.clipboardData;
      if (!dataTransfer || !dataTransfer.items) { return; }
       
      /** @type {DataTransferItem|void} */
      var item = dataTransfer.items[0];
      if (!item) { return; }
      
      /** @type {File|void} */
      var file = item.getAsFile();
      if (!file) { return; }

      if (!file.name && file.type) {
        var ext = file.type.split('/')[1];
        file.name = 'untitled.' + ext;
      }

      r.actions.trigger(ACTION_NAME, {
        target: eventTarget,
        eventDetail: 'paste',
        file: file,
      });
      e.preventDefault();
    });
  }

  /**
   * Binds an image-upload action to the 'drop' event of target element
   * @param  {HTMLElement} target
   * @param  {HTMLElement|void} eventTarget - element to use as the target in
   *                                          the event (defaults to target)
   */
  r.actions.bindImageUploadOnDrop = function(target, eventTarget) {
    eventTarget = eventTarget || target;
    var lastDragenterTarget;

    $(target).on('drop', function(e) {
      lastDragenterTarget = null;

      $(target).trigger('file-input:drop');

      /** @type {DataTransferItem} */
      var dataTransfer = e.originalEvent.dataTransfer;
      if (!dataTransfer || !dataTransfer.files) { return; }

      /** @type {File|void} */
      var file = dataTransfer.files[0];
      if (!file) { return; }

      r.actions.trigger(ACTION_NAME, {
        target: eventTarget,
        eventDetail: 'drop',
        file: file,
      });
      e.preventDefault();
    });

    // We need to preventDefault on dragenter and dragover events for
    // the browser to recognize the target as valid for drop events.
    // Additionally we need to keep track of dragenter and dragleave events
    // to know when to apply/remove the css class for style changes
    $(target).on('dragenter', function(e) {
      if (!lastDragenterTarget) {
        $(target).trigger('file-input:dragenter');
      }
      lastDragenterTarget = e.target;
      e.preventDefault();
    });

    $(target).on('dragover', function(e) {
      e.preventDefault(); 
    });

    $(target).on('dragleave', function(e) {
      if (e.target === lastDragenterTarget) {
        $(target).trigger('file-input:dragleave');
        lastDragenterTarget = null;
      }
      e.preventDefault();
    }); 
  }
}(r);
