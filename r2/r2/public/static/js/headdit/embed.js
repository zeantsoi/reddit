r.svgs = {
    index: {},
    set: function(data) {
        this.index[data[0].name] = data[0].template
    },
    make: function(name) {
        return $(r.svgs.index[name]).filter('svg')
    }
}

r.headditEmbed = {}

r.headditEmbed.init = function() {
    var vid = this.vid = $('<video id="videoel" width="300" height="225" preload="auto" loop="">').appendTo('body')[0]
    this.overlay = $('<canvas id="overlay" width="300" height="225">').appendTo('body')[0]

    // FIXME
    var snoo = location.hash == '#gold' ? '../headdit/snoo-head-gold' : '../headdit/snoo-head'
    this.snooOverlay = r.svgs.make(snoo).attr('id', 'snoo-head').appendTo('body')[0]
    this.overlayCC = overlay.getContext('2d')

    var ctrack = this.ctrack = new clm.tracker({useWebGL: true})
    this.ctrack.init(pModel)

    var getUserMedia = navigator.getUserMedia || navigator.webkitGetUserMedia || navigator.mozGetUserMedia || navigator.msGetUserMedia
    if (getUserMedia) {
        var videoSelector = {video : true}
        if (navigator.appVersion.match(/Chrome\/(.*?) /)) {
            var chromeVersion = parseInt(navigator.appVersion.match(/Chrome\/(\d+)\./)[1], 10)
            if (chromeVersion < 20) {
                videoSelector = "video"
            }
        }

        getUserMedia.call(navigator, videoSelector, _.bind(function(stream) {
            if (vid.mozCaptureStream) {
                vid.mozSrcObject = stream
            } else {
                var URL = window.URL || window.webkitURL || window.msURL || window.mozURL
                vid.src = (URL && URL.createObjectURL(stream)) || stream
            }
            vid.play()

            ctrack.start(vid)
            setInterval(_.bind(this.processSingleFrame, this), 1000)
        }, this), function() {
            alert("there was some problem trying to fetch video from your webcam. if you have a webcam, please make sure to accept when the browser asks for access to your webcam.")
            return
        })
    } else {
        alert("headdit requires getUserMedia, which your browser does not seem to support. bummer! :(")
        return
    }

    this.kittyWorker = new Worker('/mediaembed/headdit_kittyworker.js')
    this.kittyWorker.addEventListener('message', _.bind(this.handleKittyStatus, this), false)
    this.kittyWorking = false
    this.kittyFoundCount = 0

    this.lastPos = null
    this.lastY = 0
    this.deltaY = Array(2)
    this.lastDir = null
    this.lastDirChanges = [0, 0, 0]

    setInterval(_.bind(this.handleFrame, this), 50)
}

r.headditEmbed.runCommand = function(cmd) {
    window.parent.postMessage(cmd, '*')
}

r.headditEmbed.drawSnoo = function(pos, cp) {
    var svgdoc = this.snooOverlay
    $('#head', svgdoc).attr('transform', 'translate(' + pos[33][0] + ',' + pos[33][1] + ') scale(' + (pos[14][0] - pos[0][0])/67 + ')')
    $('#leyebrow, #reyebrow', svgdoc).attr('transform', 'translate(0,' + Math.min(5, Math.max(0, 2 - cp[8])) + ')')
    if (cp[6] < -6) {
        $('#mouth', svgdoc).css('opacity', 0)
        $('#mouth-agape', svgdoc).css('opacity', 1)
    } else {
        $('#mouth', svgdoc).css('opacity', 1)
        $('#mouth-agape', svgdoc).css('opacity', 0)
    }
}

r.headditEmbed.handleFrame = function() {
    this.overlayCC.clearRect(0, 0, 400, 300)
    var pos = this.ctrack.getCurrentPosition()
    var cp = this.ctrack.getCurrentParameters()
    if (pos) {
        this.lastPos = pos
        this.ctrack.draw(overlay)
        r.headditEmbed.drawSnoo(pos, cp)
    }
    $(this.snooOverlay).attr('class', !!pos ? 'located': '')

    var cmd
    if (pos && pos[41]) {
        var refY = pos[41][1]
        this.deltaY.unshift(this.lastY - refY)
        this.deltaY.pop()
        if (Math.abs(refY - this.lastY) > 2) {
            var dir = refY > this.lastY
            if (dir != this.lastDir) {
                var now = Date.now()
                this.lastDir = dir
                this.lastDirChanges.push(now)
                this.lastDirChanges.shift()
                if (now - this.lastDirChanges[0] < 1000) {
                    cmd = "upvote"
                    this.lastDir = null
                }
            }
        } else {
            if (_.all(this.deltaY, function(v) { return Math.abs(v) < .5 })) {
                if (this.lastDir != null) {
                    cmd = this.lastDir ? "prev" : "next"
                    this.lastDir = null
                } else if (cp[8] < 0 && cp[7] > 2) {
                    cmd = "downvote"
                } else if (cp[6] < -8 && cp[8] > 7) {
                    cmd = "open"
                }
            }
        }

        this.lastY = refY
    }

    if (cmd) {
        r.headditEmbed.runCommand(cmd)
    }
}

r.headditEmbed.processSingleFrame = function() {
    var scratch = document.createElement('canvas')
    scratch.width = $(this.vid).width()
    scratch.height = $(this.vid).height()
    var ctx = scratch.getContext('2d')
    ctx.drawImage(this.vid, 0, 0, scratch.width, scratch.height)
    var resizes = kittydar.getAllSizes(scratch, 48)

    if (!this._kittyWorking) {
        this._kittyWorking = true
        this.kittyWorker.postMessage(resizes)
    }

    var teamScore = this.sampleTeamColor(ctx.getImageData(0, 0, scratch.width, scratch.height))
    if (teamScore > 3) {
        r.headditEmbed.runCommand('orangered')
    } else if (teamScore < -3) {
        r.headditEmbed.runCommand('periwinkle')
    }
}

r.headditEmbed.sampleTeamColor = function(imageData) {
    var sampleCount = 20000
    var reds = []
    var avgRed = 0
    var blues = []
    var avgBlue = 0
    for (var samples=sampleCount; samples > 0; samples--) {
        var index = _.random(imageData.data.length / 4)
        var red = imageData.data[index * 4]
        var blue = imageData.data[index * 4 + 2]
        reds.push(red)
        avgRed += red
        blues.push(blue)
        avgBlue += blue
    }
    avgRed /= sampleCount
    avgBlue /= sampleCount

    var avgTint = avgRed - avgBlue
    var score = 0
    for (var i=0; i < sampleCount; i++) {
        if (Math.abs(Math.abs(reds[i] - blues[i]) - avgTint) > 50) {
            score += reds[i] - blues[i]
        }
    }
    return score / sampleCount
}

r.headditEmbed.handleKittyStatus = function(ev) {
    if (!this.lastPos) {
        return true
    }

    var nosePos = this.lastPos[41]
    var kittyFound = !!_.find(ev.data, function(kittyInfo) {
        if (   nosePos[0] > kittyInfo.x && nosePos[0] < (kittyInfo.x + kittyInfo.width)
            && nosePos[1] > kittyInfo.y && nosePos[1] < (kittyInfo.y + kittyInfo.height)) {
            console.log('are you a kitty?', nosePos, kittyInfo)
        } else {
            return kittyInfo
        }
    })

    if (kittyFound) {
        this.kittyFoundCount++
    } else {
        this.kittyFoundCount = 0
    }

    if (this.kittyFoundCount > 2) {
        r.headditEmbed.runCommand('kitty')
    }

    this._kittyWorking = false
}

$(function() {
    r.headditEmbed.init()
})
