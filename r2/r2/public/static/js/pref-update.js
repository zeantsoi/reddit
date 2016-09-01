!function(r) {
  r.pref = {
    post: function(form) {
      var email = $('input[name="email"]', form.$el).val();
      var apiTarget = form.$el.attr('action');

      var params = form.serialize();
      params.push({name:'api_type', value:'json'});

      return r.ajax({
        url: apiTarget,
        type: 'POST',
        dataType: 'json',
        data: params,
        xhrFields: {
          withCredentials: true,
        },
      });
    }
  };

  r.pref.ui = {
    init: function() {
      $('.pref-form').each(function(i, el) {
        new r.pref.ui.PrefUpdateForm(el);
      });
    },
  };

  r.pref.ui.PrefUpdateForm = function() {
    r.ui.Form.apply(this, arguments)
    this.$email = this.$el.find('input[name="email"]');
    this.$email.one('focus', this.loadCaptcha.bind(this, 'prefupdate'));
  };

  r.pref.ui.PrefUpdateForm.prototype = $.extend(new r.ui.Form(), {
    _submit: function() {
      return r.pref.post(this);
    },
  });
}(r);
