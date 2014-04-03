r.resAdvisory = {}

r.resAdvisory.minResVersion = [4, 3, 2, 1]

r.resAdvisory.checkRESClick = function(e) {
    if (e.target.id == 'viewImagesButton' || $(e.target).hasClass('expando-button')) {
        if (!r.resAdvisory.checkRESVersion()) {
            e.preventDefault()
            e.stopPropagation()
            alert("The version of Reddit Enhancement Suite you are using has a bug which makes expanding posts insecure to use. Please update Reddit Enhancement Suite to continue using post expandos.")
        } else {
            document.body.removeEventListener('click', r.resAdvisory.checkRESClick, true)
        }
    }
}

r.resAdvisory.checkRESVersion = _.memoize(function() {
    var has_res = $('#RESMainGearOverlay').length
    if (!has_res) {
        return true
    }
    var version = $('#RESConsoleVersion').text()
    if (!version) {
        return false
    }
    // Version is in the format of v1.2.3
    version = version.substring(1).split('.')
    version = _.map(version, function(x) { return parseInt(x) })
    return version >= r.resAdvisory.minResVersion
})

r.resAdvisory.init = function() {
    if (document.body.addEventListener) {
        document.body.addEventListener('click', r.resAdvisory.checkRESClick, true)
    }
}
