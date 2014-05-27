r.utils = {
    clamp: function(val, min, max) {
        return Math.max(min, Math.min(max, val))
    },

    staticURL: function (item) {
        return r.config.static_root + '/' + item
    },

    s3HTTPS: function(url) {
        if (location.protocol == 'https:') {
            return url.replace('http://', 'https://s3.amazonaws.com/')
        } else {
            return url
        }
    },

    joinURLs: function(/* arguments */) {
        return _.map(arguments, function(url, idx) {
            if (idx > 0 && url && url[0] != '/') {
                url = '/' + url
            }
            return url
        }).join('')
    },

    tup: function(list) {
        if (!_.isArray(list)) {
            list = [list]
        }
        return list
    },

    structuredMap: function(obj, func) {
        if (_.isArray(obj)) {
            return _.map(obj, function(value) {
                return r.utils.structuredMap(value, func)
            })
        } else if (_.isObject(obj)) {
            var mapped = {}
            _.each(obj, function(value, key) {
                mapped[func(key, 'key')] = r.utils.structuredMap(value, func)
            })
            return mapped
        } else {
            return func(obj, 'value')
        }
    },

  unescapeJson: function(json) {
    return r.utils.structuredMap(json, function(val) {
      if (_.isString(val)) {
        return _.unescape(val)
      } else {
        return val
      }
    })
  },

    querySelectorFromEl: function(targetEl, selector) {
        return $(targetEl).parents().addBack()
            .filter(selector || '*')
            .map(function(idx, el) {
                var parts = [],
                    $el = $(el),
                    elFullname = $el.data('fullname'),
                    elId = $el.attr('id'),
                    elClass = $el.attr('class')

                parts.push(el.nodeName.toLowerCase())

                if (elFullname) {
                    parts.push('[data-fullname="' + elFullname + '"]')
                } else {
                    if (elId) {
                        parts.push('#' + elId)
                    } else if (elClass) {
                        parts.push('.' + _.compact(elClass.split(/\s+/)).join('.'))
                    }
                }

                return parts.join('')
            })
            .toArray().join(' ')
    },

    serializeForm: function(form) {
        var params = {}
        $.each(form.serializeArray(), function(index, value) {
            params[value.name] = value.value
        })
        return params
    },

    _pyStrFormatRe: /%\((\w+)\)s/g,
    pyStrFormat: function(format, params) {
        return format.replace(this._pyStrFormatRe, function(match, fieldName) {
            if (!(fieldName in params)) {
                throw 'missing format parameter'
            }
            return params[fieldName]
        })
    },

    _mdLinkRe: /\[(.*?)\]\((.*?)\)/g,
    formatMarkdownLinks: function(str) {
        return _.escape(str).replace(this._mdLinkRe, function(match, text, url) {
            return '<a href="' + url + '">' + text + '</a>'
        })
    },

    prettyNumber: function(number) {
        // Add commas to separate every third digit
        var numberAsInt = parseInt(number)
        if (numberAsInt) {
            return numberAsInt.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",")
        } else {
            return number
		}
	},

    LRUCache: function(maxItems) {
        var _maxItems = maxItems > 0 ? maxItems : 16
        var _cacheIndex = []
        var _cache = {}

        var _updateIndex = function(key) {
            _deleteFromIndex(key)
            _cacheIndex.push(key)
            if (_cacheIndex.length > _maxItems) {
                delete _cache[_cacheIndex.shift()]
            }
        }

        var _deleteFromIndex = function(key) {
            var index = _.indexOf(_cacheIndex, key)
            if (index >= 0) {
                _cacheIndex.splice(index, 1)
            }
        }

        this.remove = function(key) {
            _deleteFromIndex(key)
            delete _cache[key]
        }

        this.set = function(key, data) {
            if (_.isUndefined(data)) {
                this.remove(key)
            } else {
                _cache[key] = data
                _updateIndex(key)
            }
        }

        this.get = function(key) {
            var value = _cache[key]
            if (!_.isUndefined(value)) {
                _updateIndex(key)
            }
            return value
        }

        this.ajax = function(key, options) {
            var cached = this.get(key)
            if (!_.isUndefined(cached)) {
                return (new $.Deferred()).resolve(cached)
            } else {
                return $.ajax(options).done(_.bind(this.set, this, key))
            }
        }
    }

}

// Nothing is true. Everything is permitted.
String.prototype.format = function (params) {
    return r.utils.pyStrFormat(this, params)
}
