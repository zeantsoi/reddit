!function(r) {
    r.survey = {}

    r.survey.init = function() {
        if (!$.cookie('survey_action')){
            $('.survey-overlay').slideToggle({
                direction: 'up',
            }, 300);

            $(document.body).on('click', '.survey-decline, .survey-accept', function(e) {
                var expiry_date = new Date();
                var hours = 730; // approx 1 month
                expiry_date.setTime(expiry_date.getTime() + (hours * 3600 * 1000));
                $.cookie('survey_action', '1', {domain: r.config.cur_domain, expires: expiry_date, path: '/'})
                $('.survey-overlay').slideToggle({
                    direction: 'down',
                }, 300);

                var payload = {
                    'survey_name': $(this.closest('.survey-overlay')).data(name),
                };

                var defaultFields = [
                  'page_type',
                  'listing_name',
                ];

                if ($(this).hasClass('survey-accept')){
                    r.analytics.sendEvent('survey_events', 'survey_accepted', defaultFields, payload);
                } else if ($(this).hasClass('survey-decline')){
                    r.analytics.sendEvent('survey_events', 'survey_declined', defaultFields, payload);
                }
            });
        }
    }

    $(function() {
        r.hooks.get('reddit').register(r.survey.init);
    });
}(window.r);

