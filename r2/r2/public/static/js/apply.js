console.log('want to be a frontend developer at reddit? job.apply() for details.')

function job() {
    function frob(s, n) {
        return _.map(s, function(c) {
            return String.fromCharCode(c.charCodeAt(0) + n)
        }).join('')
    }

    var $el = $(this)
    if (!$el.is('#header')) {
        throw 'error: `this` must be the element with id="header".'
    }

    $el
        .find('#header-bottom-left')
        .css('background', '#cee3f8')
        .prepend(
            $('<div>')
                .append('<img src="http://redditstatic.com/triforce.gif">')
                .append('<p>reddit is seeking a creative frontend developer to join forces with in San Francisco.</p>')
                .append('<hr>')
                .append('<p>sound like fun?</p>')
                .append('<p><a href="mailto:' + frob('wpfghkpgfBtgffkv0eqo', -2) + '">tell us about yourself.<a></p>')
                .css({'font-size': '30px', 'text-align': 'center', 'padding': '20px 40px', 'line-height': 0, 'opacity': 0})
                .animate({'line-height': 1.25, 'opacity': 1})
        )

    return ';]'
}
