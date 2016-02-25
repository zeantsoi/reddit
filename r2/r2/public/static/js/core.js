!function($) {
  var MAX_LOG_COUNT = 3;
  var PAGE_AGE_LIMIT = 5 * 60;  // seconds
  var SEND_THROTTLE = 8;  // seconds
  var WEB_ERROR_LOG_API = '/web/log/error.json';

  var _config = null;
  var _logCount = 0;
  var _preConfigLogQueue = [];
  var _queuedLogs = [];

  var _clientLog = window.console ? console.log.bind(console) : function() {};

  var r = {};

  var rCore = {

    setConfig: function(config) {
      // TODO - replace r.setup(...) with r.core.setConfig(...)
      config.currentOrigin = location.protocol+'//'+location.host
      _config = config;
      r.config = config;
      
      _preConfigLogQueue.forEach(rCore.serverLog);
      delete _preConfigLogQueue;
    },

    wrapSource: function(className, fileName, fn) {
      // used in js.py to wrap sources with, producing:
      // r.core.wrapSource("FileSource", "uuid.js", function(r, $) { <content> });
      try {
        fn(r, $);
      } catch (err) {
        rCore.serverLog('Error in', className, fileName, ':', err.toString());
      }
    },

    serverLog: function(/* args */) {
      if (_logCount >= MAX_LOG_COUNT) {

        rCore.clientLog('Not sending debug log; already sent', _logCount);

      } else if (!_config) {

        if (!_preConfigLogQueue) {
          // This should never happen
          rCore.clientLog('Not queueing debug log; _preConfigLogQueue does not exist');
        } else if (_preConfigLogQueue.length < MAX_LOG_COUNT) {
          var args = Array.prototype.slice.call(arguments);        
          _preConfigLogQueue.push(args);
        } else {
          rCore.clientLog('Not queueing debug log; _preConfigLogQueue full');
        }

      } else if (!_config.send_logs) {

        rCore.clientLog('Server-side debug logging disabled');

      } else if (Math.abs(_getPageAge()) > PAGE_AGE_LIMIT) {
        // Don't send messages for pages older than 5 minutes to prevent CDN 
        // cached pages from slamming us if we need to turn off logs.

        rCore.clientLog('Not sending debug log; page too old:', pageAge);

      } else {

        var message = Array.prototype.slice.call(arguments).join(' ');
        _queueServerLog(message);
        rCore._asyncSendLogs();

      }
    },

    clientLog: function(/* args */) {
      var message = Array.prototype.slice.call(arguments).join(' ');
      _clientLog(message);
    },

    ajax: function(request) {
      if (_isLocalUrl(request.url)) {
        request.headers = request.headers || {};
        request.headers['X-Modhash'] = _config.modhash;
      }

      return $.ajax(request);
    },

    _asyncSendLogs: _throttle(function() {
      var queueCount = _queuedLogs.length;
      var logs;

      if (!queueCount) {
        return;
      }

      try {
        logs = JSON.stringify(_queuedLogs);
      } catch (err) {
        rCore.clientLog('Error parsing error logs', _queuedLogs);
      }

      _queuedLogs.length = 0;

      if (!logs) {
        return;
      }

      rCore.ajax({
        type: 'POST',
        url: WEB_ERROR_LOG_API,
        data: {
          logs: logs,
        },
        headers: {
          'X-Loggit': true,
        },
        success: function() {
          rCore.clientLog('Sent', queueCount, 'debug logs to server');
        },
        error: function(xhr, err, status) {
          rCore.clientLog('Error sending debug logs to server:', err, ';', status)
        },
      });
    }, SEND_THROTTLE),

  };


  function _throttle(fn, wait) {    
    // We don't necessarily want underscore as a dependency yet, but we do need
    // a throttle function for rCore.severLog.  This is a greatly simplified
    // version of underscore's throttle method, with the main difference being
    // that it is _always_ async - if you call this in an infinite loop, the
    // throttled function will never actually fire.
    var _timeout;
    
    return function() {
      if (_timeout) { return; }

      var context = this;
      var args = arguments;
      
      _timeout = window.setTimeout(function() {
        fn.apply(context, args);
        _timeout = null;
      }, wait);
    };
  }


  function _getPageAge() {
    if (!_config) {
      return 0;
    } else {    
      return (new Date / 1000) - _config.server_time;
    }
  }

  function _isLocalUrl(url) {
    if (!_config || !url) {
      return;
    } else {
      return url[0] == '/' || url.lastIndexOf(_config.currentOrigin, 0) == 0;
    }
  }

  function _queueServerLog(message) {
    var logData = {
      url: window.location.toString(),
      msg: message,
    };
    _queuedLogs.push(logData);
    _logCount += 1;
  }

  // alias old setup method to prevent transient errors
  r.setup = rCore.setConfig;

  r.core = rCore;
  window.r = r;
}(jQuery);
