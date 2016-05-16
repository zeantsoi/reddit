!function(r) {
  var URL = window.URL || window.webkitURL;
  var MAX_STATIC_UPLOAD_SIZE_MB = 20;
  var MAX_GIF_UPLOAD_SIZE_MB = 100;
  var MB_TO_BYTES = Math.pow(1024, 2);

  r.newlinkController = {
    VALID_DROP_STATE: 'image-upload-drop-active',
    DROP_TARGET_CLASS: 'image-upload-drop-target',
    VALID_FILE_TYPES: /^image\/(png|jpe?g|gif)$/,
    VALID_URL: /^https?:\/\/([\da-z\.-]+)\.([a-z\.]{2,6})([\/\w \.-]*)*\/?$/,
    IS_LOCAL_PREVIEW_SUPPORTED: URL && URL.createObjectURL && URL.revokeObjectURL,
    SUGGEST_TITLE_DEBOUNCE_RATE: 500,

    _suggestedUrl: '',
    _suggestedTitle: '',
    _leaseReq: null,
    _uploader: null,
    _mimetype: null,
    _fileType: null,
    _fileSource: null,

    isSupported: function() {
      return (
        r.S3ImageUploader.isSupported() &&
        window.FileReader &&
        window.Uint8Array
      );
    },

    init: function() {
      this._debouncedRequestSuggestTitle = _.debounce(this._requestSuggestTitle, this.SUGGEST_TITLE_DEBOUNCE_RATE);

      this.form = document.getElementById('newlink');

      if (!this.form) { return; }

      this.$form = $(this.form);
      this.$submitButton = this.$form.find('button[name=submit]');
      this.$urlField = $('#url-field');
      this.$throbber = this.$urlField.find('.new-link-preview-throbber');
      this.$typeInput = this.$urlField.find('input[name=kind]');

      this.$urlInputDisplayGroup = $('#new-link-url-input');
      this.$urlInput = this.$urlInputDisplayGroup.find('input[name=url]');
      this.$clearUrlButton = this.$urlInputDisplayGroup.find('.clear-input-button');

      this.$fileInputDisplayGroup = $('#new-link-image-input');
      this.$fileInput = this.$fileInputDisplayGroup.find('input[type=file]');

      this.$imageNameDisplayGroup = $('#new-link-image-name-display');
      this.$imageNameDisplayText = this.$imageNameDisplayGroup.find('#image-name');
      this.$clearImageButton = this.$imageNameDisplayGroup.find('.clear-input-button');

      this.$titleInput = $('#title-field textarea[name=title]');
      this.$suggestTitleButton = $('#suggest-title a');

      this.$previewLinkDisplayGroup = $('#new-link-preview');
      this.$previewLinkTitle = this.$previewLinkDisplayGroup.find('.new-link-preview-title');
      this.$previewLinkDomain = this.$previewLinkDisplayGroup.find('.new-link-preview-domain');

      this.$previewImageDisplayGroup = $('#new-link-image-preview');

      this.$urlInput.on('input', function(e) {
        if (e.target.value) {
          this._handleUrlInput(e.target.value);
        } else {
          this._handleUrlClear();
        }
      }.bind(this));

      this.$clearUrlButton.on('click', function(e) {
        this.$urlInput.val('');
        this._handleUrlClear();
      }.bind(this));
      
      this.$titleInput.on('input', function(e) {
        this._handleTitleChange(e.target.value);
      }.bind(this));

      this.$suggestTitleButton.on('click', function(e) {
        if (!this._suggestedTitle) { return; }

        this.$titleInput.val(this._suggestedTitle);
        this._handleTitleChange(this._suggestedTitle);
      }.bind(this));

      if (this.isSupported()) {
        this.$fileInputDisplayGroup.show();
        
        // Bind various forms of file input to the file-input action
        // see file-input-actions.js
        r.actions.bindImageUploadOnInput(this.$fileInput[0], this.form);
        r.actions.bindImageUploadOnDrop(this.$urlField[0], this.form);
        r.actions.bindImageUploadOnPaste(window, this.form);

        this.$urlField.addClass(this.DROP_TARGET_CLASS);

        r.actions.on('file-input', function(e) {
          if (!this._isValidAction(e)) {
            return;
          } else if (!this._isFileInputAllowed()) {
            e.preventDefault();
          }
        }.bind(this));

        r.actions.on('file-input:success', function(e) {
          if (this._isValidAction(e)) {
            // file validation is async because it goes through a FileReader to
            // verify the file's extension matches it's actual mime type
            this._fileSource = e.eventDetail;
            this._validateFileType(e.file)
            .done(function(file) {
              this._renderErrors(null);
              this._handleFileInput(file);
            }.bind(this))
            .fail(function(err) {
              this._renderErrors([err]);
            }.bind(this));
          }
        }.bind(this));

        this.$clearImageButton.on('click', function(e) {
          this._handleFileClear();
        }.bind(this));

        r.actions.on('file-input:complete', function(e) {
          if (this._isValidAction(e)) {
            this.$fileInput.resetInput();
          }
        }.bind(this));

        this.$urlField.on('file-input:dragenter', function(e) {
          if (this._isFileInputAllowed()) {
            $(e.target).addClass(this.VALID_DROP_STATE);
          }
        }.bind(this));

        this.$urlField.on('file-input:dragleave file-input:drop', function(e) {
          $(e.target).removeClass(this.VALID_DROP_STATE);
        }.bind(this));
      } else {
        this.$fileInputDisplayGroup.empty();
      }
    },
    
    _handleUrlInput: function(url) {
      this.$fileInputDisplayGroup.hide();
      if (this._isValidUrl(url)) {
        this._debouncedRequestSuggestTitle(url);
      }
    },

    _handleUrlClear: function() {
      this._suggestedUrl = '';
      this._renderErrors(null);
      this.$throbber.hide();
      this.$fileInputDisplayGroup.show();
      this.$previewLinkDisplayGroup.hide();
      this.$previewLinkTitle.text('');
      this.$previewLinkDomain.attr('href', '#').text('');
    },

    _handleTitleChange: function(title) {
      if (this._suggestedTitle && title !== this._suggestedTitle) {
        this.$suggestTitleButton.show();
      } else {
        this.$suggestTitleButton.hide();
      }
    },

    _handleFileInput: function(file) {
      this.$urlInputDisplayGroup.hide();
      this.$fileInputDisplayGroup.hide();
      this.$imageNameDisplayGroup.show();
      this.$imageNameDisplayText.text(file.name);
      this.$form.prop('disabled', true);
      this.$submitButton.prop('disabled', true);
      this._requestS3Lease(file);
    },

    _handleFileClear: function() {
      this._file = null;
      this._leaseReq = null;
      this._uploader = null;
      this._renderErrors(null);
      this.$throbber.hide();
      this.$urlInput.val('');
      this.$urlInputDisplayGroup.show();
      this.$fileInputDisplayGroup.show();
      this.$imageNameDisplayGroup.hide();
      this.$imageNameDisplayText.text('');
      this.$previewImageDisplayGroup.hide().empty();
      this.$typeInput.val('link');
      this.$form.prop('disabled', false);
      this.$submitButton.prop('disabled', false);
    },

    _renderErrors: function(errors) {
      r.errors.clearAPIErrors(this.form);
      if (errors) {
        r.errors.showAPIErrors(this.form, errors);
      }
    },

    _requestSuggestTitle: function(url) {
      this._suggestedUrl = url;
      this.$throbber.show();

      r.ajax({
        type: 'POST',
        url: 'api/fetch_title',
        data: {
          url: url,
          api_type: 'json',
        },
      })
      .done(function(res) {
        if (url !== this._suggestedUrl) { return; }

        this._suggestedTitle = '';
        this.$suggestTitleButton.hide();
        this.$throbber.hide();

        var errs = r.errors.getAPIErrorsFromResponse(res);
        if (errs) {
          r.errors.showAPIErrors(this.form, errs);
          return;
        }

        var title = res.json.data ? res.json.data.title : '';
        var domain = this._getUrlHost(url);

        if (title) {
          this._suggestedTitle = title;
          this.$previewLinkTitle.text(title);
          this.$previewLinkDomain.attr('href', domain).text(domain);  
          this.$previewLinkDisplayGroup.show();
          this.$suggestTitleButton.show();
        } else {
          this.$previewLinkDisplayGroup.hide();
          this.$previewLinkTitle.text('');
          this.$previewLinkDomain.attr('href', '#').text('');
        }
      }.bind(this))
      .fail(function() {
        if (url !== this._suggestedUrl) { return; }

        this._suggestedUrl = '';
        this.$throbber.hide();
        this.$previewLinkDisplayGroup.hide();
        this.$previewLinkTitle.text('');
        this.$previewLinkDomain.attr('href', '#').text('');
      }.bind(this));
    },

    _requestS3Lease: function(file) {
      var leaseReq = r.S3ImageUploader.request({ file: file}, this._mimetype);
      this._leaseReq = leaseReq;
      this.$throbber.show();

      leaseReq.done(function(uploader) {
        if (leaseReq !== this._leaseReq) { return; }

        this._leaseReq = null;
        this.$throbber.hide();
        this._renderErrors(null);
        this._requestS3Upload(uploader, file);
      }.bind(this))
      .fail(function(err) {
        if (leaseReq !== this._leaseReq) { return; }

        this._handleFileClear();
        this._renderErrors([err]);
      }.bind(this));
    },

    _requestS3Upload: function(uploader, file) {
      this._uploader = uploader;
      this._file = file;
      var key = this._uploader.attributes.key;

      uploader.on('request', function(uploader) {
        if (uploader !== this._uploader) { return; }

        this.$throbber.show();

        if (this.IS_LOCAL_PREVIEW_SUPPORTED) {
          var previewUrl = URL.createObjectURL(file);
          this._makePreviewImage(previewUrl, 'local-preview-image', function(img) {
            URL.revokeObjectURL(previewUrl);
            if (uploader === this._uploader) {
              this.$previewImageDisplayGroup.empty().append(img).show();
            }
          }.bind(this));
        }
      }.bind(this));

      uploader.on('invalid error', function(uploader, errs) {
        if (uploader !== this._uploader) { return; }
        r.analytics.imageUploadEvent(this._fileType, this._file.size, this._fileSource, key, errs[0].displayName);
        this._handleFileClear();
        this._renderErrors(errs);
      }.bind(this));

      uploader.on('success', function(uploader, imageUrl) {
        if (uploader !== this._uploader) { return; }

        r.analytics.imageUploadEvent(this._fileType, this._file.size, this._fileSource, key, false);

        this.$throbber.hide();
        this.$urlInput.val(imageUrl);
        this.$typeInput.val('image');
        this.$form.prop('disabled', false);
        this.$submitButton.prop('disabled', false);
        this._uploader = null;
        $('.local-preview-image')[0].className = 'uploaded-preview-image';
      }.bind(this));

      uploader.upload();
    },

    _makePreviewImage: function(url, className, callback) {
      var img = document.createElement('img');
      img.className = className;
      img.onload = function() {
        callback(img);
      };
      img.src = url;
    },

    _getUrlHost: function(url) {
      var a = document.createElement('a');
      a.href = url;
      return a.host;
    },

    _isValidAction: function(e) {
      return e.target === this.form || $.contains(this.form, e.target);
    },

    _isFileInputAllowed: function() {
      return this.$urlField.is(':visible') && !(this._file || this._leaseReq || this._uploader);
    },

    _isValidFile: function(file) {
      return file && (file instanceof File || file instanceof Blob) && file.size > 0;
    },

    _isValidUrl: function(url) {
      return url && this.VALID_URL.test(url);
    },

    _validateFileType: function(file) {
      // http://stackoverflow.com/questions/18299806/how-to-check-file-mime-type-with-javascript-before-upload
      var d = $.Deferred();
      var fileReader = new FileReader();
      var fileType = file.type.split('/');
      if (fileType.length > 1) {
        fileType = fileType[1];
      } else {
        fileType = fileType[0];
      }

      if (!this._isValidFile(file)) {
        var err = r.errors.create('BAD_FILE_TYPE', r._('That is not a valid file.'), 'image-upload');
        d.reject(err);
        r.analytics.imageUploadEvent(fileType, file.size, this._fileSource, null, err.displayName);
        return;
      }

      fileReader.onloadend = function(e) {
        var arr = (new Uint8Array(e.target.result)).subarray(0, 4);
        var headerHex = '';

        for(var i = 0; i < arr.length; i++) {
          headerHex += arr[i].toString(16);
        }

        this._mimetype = _getMimeTypeFromFileHeaderBytes(headerHex);
        if (this._mimetype) {
          this._fileType = this._mimetype.split('/')[1]
        } else {
          this._fileType = fileType;
        }
        var isGif = this._mimetype === 'image/gif';
        var err;

        if (!this._mimetype || !this.VALID_FILE_TYPES.test(this._mimetype)) {
          err = r.errors.create('BAD_FILE_TYPE', r._('That file type is not allowed'), 'image-upload');
        } else if (isGif && file.size > MAX_GIF_UPLOAD_SIZE_MB * MB_TO_BYTES) {
          var errStr = r._('Gif is too big. Maximum gif size is %(maxSize)s.').format({
            maxSize: MAX_GIF_UPLOAD_SIZE_MB + 'mb',
          });
          err = r.errors.create('BAD_FILE_SIZE', errStr);
          r.analytics.imageUploadEvent(this._fileType, file.size, this._imageSource, null, err.displayName);
        } else if (!isGif && file.size > MAX_STATIC_UPLOAD_SIZE_MB * MB_TO_BYTES) {
          var errStr = r._('Image is too big. Maximum image size is %(maxSize)s.').format({
            maxSize: MAX_STATIC_UPLOAD_SIZE_MB + 'mb',
          });
          err = r.errors.create('BAD_FILE_SIZE', errStr);
          r.analytics.imageUploadEvent(this._fileType, file.size, this._imageSource, null, err.displayName);
        }

        if (err) {
          d.reject(err);
          r.analytics.imageUploadEvent(this._fileType, file.size, this._imageSource, null, err.displayName);
        } else {
          d.resolve(file);
        }
      }.bind(this);

      fileReader.readAsArrayBuffer(file);
      return d.promise();
    },
  };


  function _getMimeTypeFromFileHeaderBytes(headerHex) {
    switch (headerHex) {
      case "89504e47":
        return "image/png";
      case "47494638":
        return "image/gif";
      default:
        // JPEG support is a lot messier than the other formats
        // https://en.wikipedia.org/wiki/JPEG_File_Interchange_Format
        if (headerHex.slice(0, 6) === "ffd8ff") {
          return "image/jpeg";
        }
    }
  }

  $(function() {
    r.newlinkController.init();
  });
}(r);
