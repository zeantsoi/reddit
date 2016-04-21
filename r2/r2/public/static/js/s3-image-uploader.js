!function(r) {
  var MAX_UPLOAD_SIZE_MB = 20;
  var UPLOAD_LEASE_ENDPOINT = '/api/image_upload_s3.json';

  var DEFAULT_ERROR_NAME = 'BAD_IMAGE_UPLOAD';
  var LEASE_REQ_FAILED_ERROR = 'BAD_LEASE_REQUEST';
  var BAD_FILE_SIZE_ERR = 'BAD_FILE_SIZE';
  var DEFAULT_ERROR_MESSAGE = r._('something went wrong.');

  /**
   * A constructor for managing client side S3 image uploads.
   *
   * Uploading images is a 2 step process:
   *   1. reddit API request to uptain an upload lease for uploading to s3
   *   2. uploading to s3
   *
   * Some useful static methods:
   *   S3ImageUploader.isSupported():Boolean
   *       to check for browser support before using.
   *   S3ImageUploader.request(params):Promise
   *       requests a lease, returns a promise that resolves with the uploader
   *       instance or rejects with an error object
   */
  var S3ImageUploader = Backbone.Model.extend({
    defaults: {
      file: null,
    },

    validators: [
      _IsFormDataSupported(),
      _IsValidFileSize('file', MAX_UPLOAD_SIZE_MB),
    ],

    validate: function(attrs) {
      return r.models.validators.validate(this, this.validators);
    },

    sync: function() {
      throw new Error('Invalid action');
    },

    setLease: function(lease) {
      this.lease = lease;

      lease.fields.forEach(function(field) {
        var name = field.name;
        var value = field.value;
        if (value === '' || value === null) {
          this.unset(name);
        } else {
          this.set(name, value);
        }
      }, this);
    },

    upload: function() {
      var err = this.validate();

      if (err) {
        this.trigger('invalid', this, [err]);
        return;
      }

      var formData = this._toFormData();
      this.trigger('request', this);

      $.ajax({
        url: this.lease.action,
        type: 'POST',
        contentType: false,
        processData: false,
        data: formData,
        dataType: 'xml',
        
        success: function(xmlResponse) {
          this.url = $(xmlResponse).find('Location').text();
          this.trigger('success', this, this.url);
        }.bind(this),
        
        error: function(jqXHR, textStatus, errorThrown) {
          var error;

          if (jqXHR.responseXML) {
            try {
              var $xml = $(jqXHR.responseXML);
              var errorText = $xml.find('Message').text();
              error = r.errors.create(DEFAULT_ERROR_NAME, errorText);
            } catch (err) {
              // let this fall through to the if block below
            }
          }

          if (!error) {
            error = r.errors.create(DEFAULT_ERROR_NAME, errorThrown || DEFAULT_ERROR_MESSAGE);
          }

          this.trigger('error', this, [error]);
        }.bind(this),
        
        progress: function(e) {
          if (e.loaded || e.total) {
            this.trigger('progress', this, e.loaded, e.total);
          }
        }.bind(this),
        
        complete: function() {
          this.trigger('complete', this);
        }.bind(this),
        
        xhr: function() {
          var xhr = $.ajaxSettings.xhr();

          if (xhr instanceof window.XMLHttpRequest) {
            xhr.addEventListener('progress', this.progress, false);
          } else if (xhr.upload) {
            xhr.upload.addEventListener('progress', this.progress, false);
          }

          return xhr;
        },
      });
    },

    _toFormData: function() {
      var formData = new FormData();
      for (var key in this.attributes) {
        if (key !== 'file') {
          formData.append(key, this.get(key));
        }
      }
      // file needs to be the last form field
      formData.append('file', this.get('file'));
      return formData;
    },
  },

  // S3ImageUploader static methods
  {
    isSupported: function() {
      return !!window.FormData;
    },

    /**
     * Request an upload lease for a given file.  Returns a promise that 
     * resolves with an S3ImageUploader instance or rejects with an ApiError
     * @param  {Object} options needs to have at _least_ a file property
     *                          containing the file to upload, along with any
     *                          other default values
     * @return {$.Promise}
     */
    request: function(options) {
      var d = $.Deferred();

      if (!options.file) {
        d.reject(r.errors.create(LEASE_REQ_FAILED_ERROR, 'missing file option'));
        return d.promise();
      }

      r.ajax({
        url: UPLOAD_LEASE_ENDPOINT,
        type: 'POST',
        dataType: 'json',

        data: {
          filepath: options.file.name,
          ajax: true,
          raw_json: '1',
        },

        success: function(data, textStatus, jqXHR) {
          var uploader = new S3ImageUploader(options);
          uploader.setLease(data);
          d.resolve(uploader);
        },

        error: function(jqXHR, textStatus, errorThrown) {
          try {
            d.reject(r.errors.create(LEASE_REQ_FAILED_ERROR, jqXHR.responseJSON.message));
          } catch (err) {
            d.reject(r.errors.create(LEASE_REQ_FAILED_ERROR, errorThrown || DEFAULT_ERROR_MESSAGE));
          }
        },
      });

      return d.promise();
    },
  });

  function _IsValidFileSize(attrName, maxSizeMb) {
    var maxSizeBytes = maxSizeMb * Math.pow(1024, 2);
    return function(model) {
      var value = model.get(attrName);
      if (!value || !value.size) {
        return r.errors.create(BAD_FILE_SIZE_ERR, r._('No file.'));
      } else if (value.size > maxSizeBytes) {
        var errStr = r._('File is too big. Maximum file size is %(maxSize)s.').format({
          maxSize: maxSizeMb + 'mb',
        });
        return r.errors.create(BAD_FILE_SIZE_ERR, errStr);
      }
    }
  }

  function _IsFormDataSupported() {
    return function() {
      if (!window.FormData) {
        return r.errors.create(DEFAULT_ERROR_NAME, r._('File upload not supported in your browser.'));
      }
    }
  }

  r.S3ImageUploader = S3ImageUploader;
}(r);
