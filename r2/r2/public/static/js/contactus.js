var defaultTitle = "what is your issue?"; 

// Templates
var link = _.template("<a href=\"<%= url %>\"><%= text %></a>");

function reportContentTmpl(reportReason, composeURL) {
   var tmpl = _.template(
     "If you wish to report <%= reportReason %> <%= composeLink %>  with a direct " +
     "link to where the offending content appears on Reddit.");
   var anchor = link({text: "please send us a message", url: composeURL});
   return tmpl({reportReason: reportReason, composeLink: anchor});
}


reportCompanionMsg = "Remember we deal with lots of users. Please be as concise as possible and " +
                     "add any relevant links. This will enable us to deal with your report more efficiently."


// Account issue forms.
var generalAccountQForm = {
   title: "I have a general account question.",
   buttons: [{
     text: "ask the reddit community",
     action: {
       type: "link",
       content: getRedditURL("/r/help"),
     },
   },
   {
     text: "help with reddit gifts",
     action: {
       type: "link",
       content: getRedditURL("/r/secretsanta"),
     },
   },
   {
     text: "question about reddit Gold",
     action: {
       type: "link",
       content: "mailto:goldsupport@reddit.com",
     },
    },
  ],
};

// General help forms
var accountIssueForm = {
  title: "how can we help you with your account?",
  buttons: [{
    text: "hacked accounts",
    action: {
      type: "show-details",
      content: [
        "If you believe your account has been accessed by a third party please email us, " + 
        "from the email address attached to your Reddit account, at " +
        link({url: "emailto:contact@reddit.com", text: "contact@reddit.com"}) +
        ". We can investigate the issue further from there.", ],
    },
  }, 
  {
    text: "password reset",
    action: {
      type: "show-details",
      content: [
        "If you are having trouble logging in to your account you may need to go " +
        "through a password reset. You can follow " +
        link({url: "https://www.reddit.com/password", text: "this link"}) +
        " to reset your password.",
        "** Please note that you need to have a verified email address to reset your password." +
        "Without a verified email address it is not possible to reset your password " +
        "for your Reddit account.",
      ],
    },
  },
  {
    text: "banned account",
    action: {
      type: "show-details",
      content: [
        "If your account has been suspended and you wish to appeal, please reply to the PM " +
        "informing you of your ban with all the relevant details.", ],
    },
  },
  {
    text: "general account question",
    action: {
      type: "show-form",
      content: generalAccountQForm,
    },
  }, ],
};

var breakRulesForm = {
  title: "which rule does the content break?",
  buttons: [{
    text: "personal and identifiable information",
    action: {
      type: "show-details",
      content: [
        reportContentTmpl("content you feel breaks our rules on personal and identifiable information",
                          getComposeURL("Personal and confidential information")),
        reportCompanionMsg,],
    },
  },
  {
    text: "threatening, harassing, or inciting to violence",
    action: {
      type: "show-details",
      content: [
        reportContentTmpl("content you feel threatens, harasses or incites violence",
                          getComposeURL("Threatening, harassing, or inciting violence")),
        reportCompanionMsg,],
    },
  },
  {
    text: "ban evasion",
    action: {
      type: "show-details",
      content: [
        reportContentTmpl("a user for ban evasion", getComposeURL("Ban Evasion")),
        reportCompanionMsg,],
    },
  }, 
  {
    text: "vote manipulation",
    action: {
      type: "show-details",
      content: [
        reportContentTmpl("a user for vote manipulation", getComposeURL("Vote Manipulation")),
        reportCompanionMsg,],
    },
  }, ],
};

var spamHelpForm = {
  title: "how can I report spam?",
  buttons: [{
    text: "report spam",
    action: {
      type: "link",
      content: getComposeURL("Spam"),
    },
  }, ],
};

// First level admin help
var generalHelpForm = {
  title: defaultTitle,
  buttons: [{
    text: "spam",
    action: {
      type: "show-form",
      content: spamHelpForm,
    },
  },
  {
    text: "content breaks reddit\'s rules",
    action: {
      type: "show-form",
      content: breakRulesForm,
    },
  },
  {
    text: "account issue",
    action: {
      type: "show-form",
      content: accountIssueForm,
    },
  }, ]
};

var contentSettingsHelp = {
title: "how can I hide content?",
 buttons: [{
   text: "mute/hide",
   action: {
     type: "show-details",
     content: [
       "You can hide content by clicking on the hide button below any post on the site. This will remove" +
       "the content from your view.",
       "You can view and unhide your hidden posts by clicking on the hidden tab in your account overview.",],
   },
 }, {
   text: "block",
   action: {
     type: "show-details",
     content: ["You can block any user who has contacted you. You do so by clicking on the block " +
               "button beneath any PM or Comment/Post reply in your inbox.",
               "You can delete any PM in your inbox by clicking on the delete button that appears below " +
               "any PM you have received. ",],
   },
 }, ]
};

// Main form body.
var contactAdminsForm = {
  title: defaultTitle,
  buttons: [{
    text: "annoying content",
    action: {
      type: "show-form",
      content: contentSettingsHelp,
    },
  },
  {
    text: "content I don\'t want to see",
    action: {
      type: "show-form",
      content: contentSettingsHelp,
    },
  },
  {
    text: "something else",
    action: {
      type: "show-form",
      content: generalHelpForm,
    }
  }],
};

function getRedditURL(path) {
  // If the path doesn't end with `/` than it's not relative.
  if ( !path.startsWith("/")) {
    return path
  }
  loc = document.location
  return loc.protocol + "//" + loc.host + path
}   

function getComposeURL(subject) {
  return getRedditURL(
    "/message/compose?to=%2Fr%2Freddit.com&subject=" +
    encodeURIComponent(subject));
}

function makeButton(option) {
  var action = option.action;
  var $button = $(document.createElement("h2")).addClass("button").text(option.text);
  if (action.type == "link") {
    var href = getRedditURL(action.content)
    var $anchor = $(link({url: href, text: ''}));
    $anchor.append($button);
    return $anchor;
  }

  if (action.type == "show-details") {
    $button.addClass("has-details");
  } else if (action.type == "show-form") {
    var form = action.content;
    $button.on("click", function() {
      return showForm(form)});
  } else if (action.type == "html") {
    $button.append(action.content);
  } else {
    console.log("Unknown button type ' + action.type + '.");
  }

  return $button 
}
  
function showForm(form) {
  var $optionsList = $("ol.contact-options").empty();
  $(".content #page-title").text(form.title);

  for (i = 0; i < form.buttons.length; i++) {
    var newOption = form.buttons[i];
    newOption.action.content.last_form = form;

    var $optionItem = $(document.createElement("li"));
    var $button = makeButton(newOption);
    $optionItem.append($button);

    if (newOption.action.type == "show-details") {
      var $details = $(document.createElement("ol")).addClass("details");

      for (d = 0; d < newOption.action.content.length; d++) {
        var detail = newOption.action.content[d];
        var $detail = $(document.createElement("li")).append(detail);
        $details.append($detail);
      }
     $optionItem.append($details);
   }     
   $optionsList.append($optionItem);
  }
  if (form.last_form != undefined) {
    var button = {
      text: "back",
      action: {
        type: "show-form",
        content: form.last_form,
      },
    };
    $optionsList.append(makeButton(button));
  }
}
    
function setupDetailsListeners() {
  $(".contact-options").on("click", "h2.has-details", function() {
    var $toggledDetails = $(this).siblings(".details");
    if ($toggledDetails.is(":visible")) {
      $toggledDetails.slideUp();
    } else {
      $(".details").slideUp();
      $toggledDetails.slideDown();
    }
  }); 
}

function initContactPage(contactAdminForm) {
  setupDetailsListeners(); 
  $("ol.contact-options").on("click", "#message-the-admins .button", function() {
    showForm(contactAdminForm);
  });
}


initContactPage(contactAdminsForm);

