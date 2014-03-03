r.gold = {
    _googleCheckoutAnalyticsLoaded: false,

    init: function () {
        $('div.content').on(
            'click',
            'a.give-gold, .gold-payment .close-button',
            $.proxy(this, '_toggleThingGoldForm')
        )

        $('.stripe-gold').click(function(){
            $("#stripe-payment").show()
        })

        $('#stripe-payment.charge .stripe-submit').on('click', function() {
            r.gold.tokenThenPost('stripecharge/gold')
        })

        $('#stripe-payment.modify .stripe-submit').on('click', function() {
            r.gold.tokenThenPost('modify_subscription')
        })
    },

    _toggleThingGoldForm: function (e) {
        var $link = $(e.target),
            $thing = $link.thing(),
            thingFullname = $link.thing_id(),
            formId = 'gold_form_' + thingFullname,
            oldForm = $('#' + formId)

        if ($thing.hasClass('user-gilded') ||
            $thing.hasClass('deleted') ||
            $thing.find('.author:first').text() == r.config.logged) {
            return false
        }

        if (oldForm.length) {
            oldForm.toggle()
            return false
        }

        if (!this._googleCheckoutAnalyticsLoaded) {
            // we're just gonna hope this loads fast enough since there's no
            // way to know if it failed and we'd rather the form is still
            // usable if things don't go well with the analytics stuff.
            $.getScript('//checkout.google.com/files/digital/ga_post.js')
            this._googleCheckoutAnalyticsLoaded = true
        }

        if ($thing.hasClass('link')) {
            var cloneClass = 'cloneable-link'
        } else {
            var cloneClass = 'cloneable-comment'
        }

        var form = $('.gold-form.' + cloneClass + ':first').clone(),
            authorName = $link.thing().find('.entry .author:first').text(),
            passthroughs = form.find('.passthrough'),
            cbBaseUrl = form.find('[name="cbbaseurl"]').val()

        form.removeClass(cloneClass)
            .attr('id', formId)
            .find('p:first-child em').text(authorName).end()
            .find('button').attr('disabled', '')
        passthroughs.val('')
        $link.new_thing_child(form)
        form.show()

        // show the throbber if this takes longer than 200ms
        var workingTimer = setTimeout(function () {
            form.addClass('working')
            form.find('button').addClass('disabled')
        }, 200)

        $.request('generate_payment_blob.json', {thing: thingFullname}, function (token) {
            clearTimeout(workingTimer)
            form.removeClass('working')
            passthroughs.val(token)
            form.find('.stripe-gold').on('click', function() { window.open('/gold/creditgild/' + token) })
            form.find('.coinbase-gold').on('click', function() { window.open(cbBaseUrl + "?c=" + token) })
            form.find('button').removeAttr('disabled').removeClass('disabled')
        })

        return false
    },

    gildThing: function (thing_fullname, new_title, specified_gilding_count) {
        var thing = $('.id-' + thing_fullname)

        if (!thing.length) {
            console.log("couldn't gild thing " + thing_fullname)
            return
        }

        var tagline = thing.children('.entry').find('p.tagline'),
            icon = tagline.find('.gilded-icon')

        // when a thing is gilded interactively, we need to increment the
        // gilding count displayed by the UI. however, when gildings are
        // instantiated from a cached comment page via thingupdater, we can't
        // simply increment the gilding count because we do not know if the
        // cached comment page already includes the gilding in its count. To
        // resolve this ambiguity, thingupdater will provide the correct
        // gilding count as specified_gilding_count when calling this function.
        var gilding_count
        if (specified_gilding_count != null) {
            gilding_count = specified_gilding_count
        } else {
            gilding_count = icon.data('count') || 0
            gilding_count++
        }

        thing.addClass('gilded user-gilded')
        if (!icon.length) {
            icon = $('<span>')
                        .addClass('gilded-icon')
            tagline.append(icon)
        }
        icon
            .attr('title', new_title)
            .data('count', gilding_count)
        if (gilding_count > 1) {
            icon.text('x' + gilding_count)
        }

        thing.children('.entry').find('.give-gold').parent().remove()
    },

    tokenThenPost: function (dest) {
        var postOnSuccess = function (status_code, response) {
            var form = $('#stripe-payment'),
                submit = form.find('.stripe-submit'),
                status = form.find('.status'),
                token = form.find('[name="stripeToken"]')

            if (response.error) {
                submit.removeAttr('disabled')
                status.html(response.error.message)
            } else {
                token.val(response.id)
                post_form(form, dest)
            }
        }
        r.gold.makeStripeToken(postOnSuccess)
    },

    makeStripeToken: function (responseHandler) {
        var form = $('#stripe-payment'),
            publicKey = form.find('[name="stripePublicKey"]').val(),
            submit = form.find('.stripe-submit'),
            status = form.find('.status'),
            token = form.find('[name="stripeToken"]'),
            cardName = form.find('.card-name').val(),
            cardNumber = form.find('.card-number').val(),
            cardCvc = form.find('.card-cvc').val(),
            expiryMonth = form.find('.card-expiry-month').val(),
            expiryYear = form.find('.card-expiry-year').val(),
            cardAddress1 = form.find('.card-address_line1').val(),
            cardAddress2 = form.find('.card-address_line2').val(),
            cardCity = form.find('.card-address_city').val(),
            cardState = form.find('.card-address_state').val(),
            cardCountry = form.find('.card-address_country').val(),
            cardZip = form.find('.card-address_zip').val()
        Stripe.setPublishableKey(publicKey)

        if (!cardName) {
            status.text(r._('missing name'))
        } else if (!(Stripe.validateCardNumber(cardNumber))) {
            status.text(r._('invalid credit card number'))
        } else if (!Stripe.validateExpiry(expiryMonth, expiryYear)) {
            status.text(r._('invalid expiration date'))
        } else if (!Stripe.validateCVC(cardCvc)) {
            status.text(r._('invalid cvc'))
        } else if (!cardAddress1) {
            status.text(r._('missing address'))
        } else if (!cardCity) {
            status.text(r._('missing city'))
        } else if (!cardState) {
            status.text(r._('missing state or province'))
        } else if (!cardCountry) {
            status.text(r._('missing country'))
        } else if (!cardZip) {
            status.text(r._('missing zip code'))
        } else {

            status.text(reddit.status_msg.submitting)
            submit.attr('disabled', 'disabled')
            Stripe.createToken({
                    name: cardName,
                    number: cardNumber,
                    cvc: cardCvc,
                    exp_month: expiryMonth,
                    exp_year: expiryYear,
                    address_line1: cardAddress1,
                    address_line2: cardAddress2,
                    address_city: cardCity,
                    address_state: cardState,
                    address_country: cardCountry,
                    address_zip: cardZip
                }, responseHandler
            )
        }
        return false
    }
};

(function($) {
    $.gild_thing = function (thing_fullname, new_title) {
        r.gold.gildThing(thing_fullname, new_title)
        $('#gold_form_' + thing_fullname).fadeOut(400)
    }
})(jQuery)
