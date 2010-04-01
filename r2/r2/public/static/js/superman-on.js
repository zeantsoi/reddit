function is_superman() {
  return true;
}

function superman_inf() {
  return "&#8734;";
}

$(function() {
        var titleunhover = function() {
            $(this).find("a.title").next("a.censor").remove();
        };
        var titlehover = function() {
            var parent = $(this).parent();
            parent.find("a.title").next("a.censor").remove();
            parent.find("a.title")
              .after("<a class='pretty-button negative censor'>edit / censor</a>");
            parent.find("a.censor")
            .click(function() {
                    var a_censor = $(this);
                    var a_title = a_censor.prev();
                    var p_title = a_censor.parent();

                    a_censor.replaceWith("<a class='pretty-button positive save'>save</a>");
                    var save_button = p_title.find("a.save");

                    a_title.attr("contentEditable", "true")
                    .addClass("editbox")
                    .unbind();

                    save_button.click(function() {
                        var p_title = $(this).parent();
                        var title = p_title.find("a.title").html();
                            p_title.thing().store_state('title', title);
                            p_title
                                .find("a.positive").remove().end()
                                .find("a.title")
                                  .attr("contentEditable", "false")
                                  .hover(titlehover, function(){})
                                  .removeClass("editbox")
                                .end()
                                .hover(function(){}, titleunhover);
                        })
                }
                )
            .show();
        };
        $(".link a.title").hover(titlehover, function(){});
        $("p.title").hover(function(){}, titleunhover);
        $(".content").addClass("magic");
    }
    );
