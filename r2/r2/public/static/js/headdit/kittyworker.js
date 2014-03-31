function detectCats(resizes) {
    // stripped down version from kittydar to avoid canvas use
    var cats = []
    resizes.forEach(function(resize) {
      var kitties = kittydar.detectAtScale(resize.imagedata, resize.scale)
      cats = cats.concat(kitties)
    })
    cats = kittydar.combineOverlaps(cats, 0.5, 2)

    return cats
}

self.addEventListener('message', function(ev) {
    self.postMessage(detectCats(ev.data))
}, false)
