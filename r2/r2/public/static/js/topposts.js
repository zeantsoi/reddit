!(function(r) {
  var Carousel = Backbone.View.extend({
    events: {
      'click .posts-carousel__btn.left': 'prev',
      'click .posts-carousel__btn.right': 'next',
    },

    initialize: function() {
      this.$innerContainer = this.$el.find('.posts-carousel__inner');
      
      if (this.$el.hasClass('top')) {
        this.originalTop = this.$el.position().top;
        window.addEventListener('scroll', this.handleScroll.bind(this));  
      }

      var $posts = $('.top-posts__post');
      this.first = $posts[0];
      this.last = $posts[$posts.length - 1];

      this.left = this.$innerContainer.position().left - 40;
    },

    handleScroll: _.throttle(function(e) {
      var screenTop = window.scrollY;
      var fixed = 'top-fixed';
      if (screenTop >= this.originalTop && !this.$el.hasClass(fixed)) {
        this.$el.addClass(fixed);
      } else if (screenTop < this.originalTop && this.$el.hasClass(fixed)) {
        this.$el.removeClass(fixed);
      }
    }, 100),

    prev: function() {
      if (this.left === 0) { return; }
      this.left += 296;
      this.$innerContainer.css('left', this.left);
    },

    next: function() {
      var rect = this.last.getBoundingClientRect();
      if ( rect.right < window.innerWidth) { return; }
      this.left -= 296;
      this.$innerContainer.css('left', this.left);
    }
  });

  var el = $('.posts-carousel');
  if (el.length) {
    new Carousel({el: el});
  }
})(r);
