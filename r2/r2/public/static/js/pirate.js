$(function() {
    $('.pirate-bar input').on('click change keypress', _.debounce(function() {
        var enabled = $('.pirate-bar input:checked').val() == 'on'
        $.cookie('landlubber', enabled ? null : 1, {
            domain: r.config.cur_domain,
            path: '/',
            expires: 1
        })
        location.reload()
    }, 10))
})
