/*
this file is a quick fix to help detangle frontend dependencies

Describes the r.srAutocomplete UI class that queries the database 
to search autocomplete subreddit queries
 */

r.srAutocomplete = {
    selected_sr: {},
    orig_sr: ""
};

/* Mapping from keyname to keycode */
KEYS = {
    BACKSPACE: 8,
    TAB: 9,
    ENTER: 13,
    ESCAPE: 27,
    LEFT: 37,
    UP: 38,
    RIGHT: 39,
    DOWN: 40,
};

SR_NAMES_DELIM = ',';

/* 
@params {String} sr_name: text that goes inside
@returns {jQuery} a jQuery span for a button
*/
function sr_span(sr_name){
    var remove_button = $('<img src="/static/kill.png"/>')
                        .on('click', sr_remove_sr);

    return $('<span />')
            .attr({class: 'sr-span'})
            .html(sr_name)
            .append(remove_button);
}

/**** sr completing ****/
/* 
Represents the srAutocomplete cache. 

@returns: previous results if it exists. Otherwise returns a new array
*/
function sr_cache() {
    if (!$.defined(r.config.sr_cache)) {
        r.srAutocomplete.sr_cache = [];
    } else {
        r.srAutocomplete.sr_cache = r.config.sr_cache;
    }
    return r.srAutocomplete.sr_cache;
}

/*
Queries the Cassandra database for subreddit name. Updates the dropdown (UI)

Params:
@params {String} query: text to search in database

@returns: Nothing
*/
function sr_search(query) {
    query = query.toLowerCase();
    var cache = sr_cache();
    if (!cache[query]) {
        $.request(
            'search_reddit_names.json', 
            {query: query, include_over_18: r.config.over_18},
            function (r) {
                cache[query] = r.names;
                sr_update_dropdown(r.names);
        });
    }
    else {
        sr_update_dropdown(cache[query]);
    }

}

/**
Checks to see if subreddit is valid

@params {function} successFn: callback for success (found subreddit)
@params {function} failFn: callback for failure (did not find subreddit)
@params {Integer} backoff: if ratelimited, set backoff before trying again

@return {null}
**/
function sr_is_valid_subreddit(query, successFn, failFn, backoff){
    $(".SUBREDDIT_NOEXIST").text("loading...").show();
    if(!query || query === ""){
        return failFn(query);
    }
    query = query.toLowerCase();
    $.request('search_reddit_names.json', 
      {
        query: query, 
        include_over_18: r.config.over_18,
        exact: true
      },
      function (r) {
        $(".field-sr").hide();
        if(r.names.length == 1){
            $(".SUBREDDIT_NOEXIST").hide();
            successFn(query);
        } else {
            failFn(query);
        }
      },
      false, "json", false, 
      function(e){
        if(e === "ratelimit"){
            // If ratelimited, try again in 1/3 of a second
            if(typeof backoff === "undefined"){backoff = 200;}
            backoff = backoff * 2;
            backoff = Math.min(10000, backoff);
            window.setTimeout(
                sr_is_valid_subreddit.bind(this, query, successFn, failFn, backoff), 
                backoff);
        } else {
            failFn(query);
        }
      });
}

/**
* Event handler for onkeyup 
* Handles UI changes
*/
function sr_name_up(e) {
    var new_sr_name = $("#sr-autocomplete").val();
    var old_sr_name = window.old_sr_name || '';
    window.old_sr_name = new_sr_name;

    if (new_sr_name === '') {
        hide_sr_name_list();
    }
    else if (e.keyCode == KEYS.UP || e.keyCode == KEYS.DOWN || e.keyCode == KEYS.TAB) {
    }
    else if (e.keyCode == KEYS.ESCAPE && r.srAutocomplete.orig_sr) {
        $("#sr-autocomplete").val(r.srAutocomplete.orig_sr);
        hide_sr_name_list();
    }
    else if (new_sr_name != old_sr_name) {
        r.srAutocomplete.orig_sr = new_sr_name;
        sr_search($("#sr-autocomplete").val());
    }
}

function sr_name_down(e) {
    /* Event handler for onkeydown */
    var input = $("#sr-autocomplete");
    
    if (e.keyCode == KEYS.UP || e.keyCode == KEYS.DOWN || e.keyCode == KEYS.TAB) {
        var dir = e.keyCode == KEYS.UP && 'up' || 'down';
        var cur_row = $("#sr-drop-down .sr-selected:first");
        var first_row = $("#sr-drop-down .sr-name-row:first");
        var last_row = $("#sr-drop-down .sr-name-row:last");

        var new_row = null;
        if (dir == 'down' || e.keyCode == KEYS.TAB) {
            if (!cur_row.length) new_row = first_row;
            else if (cur_row.get(0) == last_row.get(0)) new_row = null;
            else new_row = cur_row.next(':first');
        }
        else {
            if (!cur_row.length) new_row = last_row;
            else if (cur_row.get(0) == first_row.get(0)) new_row = null;
            else new_row = cur_row.prev(':first');
        }
        highlight_dropdown_row(new_row);
        if (new_row) {
            input.val($.trim(new_row.text()));
        }
        else {
            input.val(r.srAutocomplete.orig_sr);
        }
        return false;
    }
    else if (e.keyCode == KEYS.ENTER) {
        sr_is_valid_subreddit(
            e.target.value, 
            sr_add_sr_then_trigger(), 
            sr_show_error_msg);
        e.target.value = "";
        hide_sr_name_list();
        return false;
    } else if (e.keyCode == KEYS.BACKSPACE){
        if(!e.target.value && Object.keys(r.srAutocomplete.selected_sr).length !== 0){
            e.preventDefault();
            $("#sr-autocomplete").trigger("sr-changed");
            var child = $("#sr-autocomplete-area > span").last();
            if (child){
                var text = child.text();
                delete r.srAutocomplete.selected_sr[text];
                child.remove();
                sr_update_selected_sr_input();
            }
        }
    }
}

function hide_sr_name_list(e) {
    $("#sr-drop-down").hide();
}

/* Event handler for when mousedown on the subreddit dropdown */
function sr_dropdown_mdown(row) {
    r.srAutocomplete.sr_mouse_row = row; //global
    return false;
}

/* Event handler for when mouseup on the subreddit dropdown */
function sr_dropdown_mup(row) {
    if (r.srAutocomplete.sr_mouse_row == row) {
        var name = $(row).text();
        sr_is_valid_subreddit(
            name, 
            sr_add_sr_then_trigger({is_autocomplete: true}), 
            sr_show_error_msg);
        $("#sr-autocomplete").val("");
        $("#sr-drop-down").hide();
    }
}

/* Called when a suggested subreddit is click */
function set_sr_name(link) {
    var name = $(link).text();
    $("#sr-autocomplete").trigger('focus');
    sr_is_valid_subreddit(
        name, 
        sr_add_sr_then_trigger({is_suggestion: true}),
        sr_show_error_msg);
}

/* UI: Adds a subreddit to the list of subreddits posted */
function sr_add_sr(sr_name){
    // Checks if sr_name is defined and doesn't exist in selected_sr yet
    if (sr_name && !(sr_name.toLowerCase() in r.srAutocomplete.selected_sr)){
        var new_sr_span = sr_span(sr_name);
        $("#sr-autocomplete").before(new_sr_span);
        r.srAutocomplete.selected_sr[sr_name] = true;
        sr_update_selected_sr_input();
    }
}

function sr_add_sr_then_trigger(trigger_params){
    return function(sr_name){
        sr_add_sr(sr_name);
        $("#sr-autocomplete").trigger("sr-changed", trigger_params);
    };
}

function sr_reset(){
    r.srAutocomplete.selected_sr = {};
    var child = $("#sr-autocomplete-area > span").last();
    while (child.length !== 0){
        child.remove();
        child = $("#sr-autocomplete-area > span").last();
    }
    sr_update_selected_sr_input();
}

/**
Displays an error message if a given subreddit is not valid
*/
function sr_show_error_msg(subreddit){
    var error_msg = "subreddit does not exist";
    if(subreddit){
        error_msg = "subreddit /r/" + subreddit + " does not exist";
    }
    $(".SUBREDDIT_NOEXIST").text(error_msg).show();
}

/**
Handles removal of a subreddit from the selected subreddit list.

Updates UI to reflect change.

@params {Event} e: event of click

@warning: Assumes a particular tree structure of the event. 
Assumes the event only occurs when the close button is clicked

*/
function sr_remove_sr(e){
    $(e.target).parent().remove();
    $("#sr-autocomplete").trigger("sr-changed");
    delete r.srAutocomplete.selected_sr[e.target.previousSibling.nodeValue];
    sr_update_selected_sr_input();
}

/**
Updates input value of the subreddits submitted
*/
function sr_update_selected_sr_input(){
    var new_string = Object.keys(r.srAutocomplete.selected_sr).join(SR_NAMES_DELIM);
    $("#selected_sr_names").val(new_string);
}

/**
* UI effect to update dropdown
**/
function sr_update_dropdown(sr_names) {
    /*
    UI effect to update dropdown
    */
    var drop_down = $("#sr-drop-down");
    if (!sr_names.length) {
        drop_down.hide();
        return;
    }

    var first_row = drop_down.children(":first");
    first_row.removeClass('sr-selected');
    drop_down.children().remove();

    // Populates dropbown
    var j = 0;
    $.each(sr_names, function(i) {
        if(sr_names[i].toLowerCase() in r.srAutocomplete.selected_sr) return;
        if (j > 10) return;
        j++;
        var name = sr_names[i];
        var new_row = $("<li />")
                        .addClass('sr-name-row')
                        .attr({
                            onmouseover: 'highlight_dropdown_row(this)',
                            onmousedown: 'return sr_dropdown_mdown(this)',
                            onmouseup: 'sr_dropdown_mup(this)'
                        });
        new_row.text(name);
        drop_down.append(new_row);
    });

    var height = $("#sr-autocomplete-area").outerHeight();
    drop_down.css('top', height);
    drop_down.show();
}

/* UI: Highlights dropdown item */
function highlight_dropdown_row(item) {
    $("#sr-drop-down").children('.sr-selected').removeClass('sr-selected');
    if (item) {
        $(item).addClass('sr-selected');
    }
}