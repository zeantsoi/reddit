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


reportWithEmailMessage = "If you do not have a Reddit account please contact us on " +
                         link({url:"mailto:contact@reddit.com", text: "contact@reddit.com"}) +
                         " with links relevant to your issue."
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
    text: "suspended account",
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
        reportWithEmailMessage,
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
        reportWithEmailMessage,
        reportCompanionMsg,],
    },
  },
  {
    text: "ban evasion",
    action: {
      type: "show-details",
      content: [
        reportContentTmpl("a user for ban evasion", getComposeURL("Ban Evasion")),
        reportWithEmailMessage,
        reportCompanionMsg,
        "** Please note: we can only accept reports of ban evasion from moderators of the " +
        "subreddit in which the evasion is taking place. If you are not a moderator and you " +
        "suspect ban evasion, please report it to the moderator of that subreddit.",],
    },
  }, 
  {
    text: "vote manipulation",
    action: {
      type: "show-details",
      content: [
        reportContentTmpl("a user for vote manipulation", getComposeURL("Vote Manipulation")),
        reportWithEmailMessage,
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
    text: "content breaks Reddit\'s rules",
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
   text: "hide",
   action: {
     type: "show-details",
     content: [
       "You can hide content by clicking on the hide button below any post on the site. This will remove " +
       "the content from your view.",
       "You can view and unhide your hidden posts by clicking on the hidden tab in your account overview.",],
   },
 }, {
   text: "block",
   action: {
     type: "show-details",
     content: ["You can block any user who has contacted you. You do so by clicking on the block button beneath " +
               "any PM or Comment/Post reply in your " +
               link({text: "inbox", url: getRedditURL("/message/inbox/")}) + ".",
               "You can delete any PM in your inbox by clicking on the delete button that appears below " +
               "any PM you have received. ",],
   },
 }, ]
};

// Contact admins form body.
var contactAdminsForm = {
  title: defaultTitle,
  buttons: [{
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

//Main form details
var advertisingDetails = [
  "Subscribe to" +
  link({url: getRedditURL("/r/selfserve"), text: "/r/selfserve"}) +
  " to talk with other advertisers about advertising on reddit.",
  "Check out " +
  link({url: getRedditURL("/r/ads"), text: "/r/ads"}) +
  "to see the most popular image ads on reddit.",
  "Reach the reddit advertising team at " +
  link({url: getRedditURL("mailto:advertising@reddit.com"), text: "advertising@reddit.com"}) + ".",
  "Learn more about advertising products and best practices a " +
  link({url: getRedditURL("/advertising"), text: "reddit.com/advertising"}) + ".",
];

var pressDetails = [
  "For guidelines on using and sourcing Reddit, please visit the Press & Media help page " +
  link({url: "https://reddit.zendesk.com/hc/en-us/articles/206630455-Press-Media", text: "here"}) + ".",
  "If you have general questions about your personal Reddit account, please email " +
  link({url: "mailto:contact@reddit.com", text: "contact@reddit.com"}) +
  " and include your Reddit username.",
  "If you have questions about licensing, reproducing, or using Reddit’s logo, screenshots, " +
  "or content for personal or business use, please contact " +
  link({url: "mailto:licensing@reddit.com", text: "licensing@reddit.com"}) + ".",
  "If you are a journalist or reporter looking to reach Reddit’s Communications team for a " +
  "story inquiry, please contact " +
  link({url: "mailto:press@reddit.com", text: "press@reddit.com"}) + ".",
];

//Main form body
var contactForm = {
  title: "how can we help you?",
  buttons: [{
    text: 'get help moderating',
    action: {
      type: 'show-details',
      content: [
        "Are you a new moderator?  Need advice?  You'll find a community ready to assist you at " +
        link({url: getRedditURL("/r/modhelp"), text: "/r/modhelp"}),
      ],
    },
  },
  {
    text: "report a bug",
    action: {
      type: "show-details",
      content: [
        "Check out " +
        link({url: getRedditURL("/r/bugs"), text: "/r/bugs"}) +
        " for other people with the same problem, or submit your own bug report.",
        "If you have an idea for a new feature, tell us about it in " +
        link({url: getRedditURL("/r/ideasfortheadmins"), text: "/r/ideasfortheadmins"}) + "."
      ],
    },
  },
  {
    text: "use the Reddit trademark",
    action: {
      type: "show-details",
      content: [
        "You'll need a license to use the reddit trademark.  Read our " +
        link({url:getRedditURL("/wiki/licensing"), text: "licensing page"}) +
        " to find out how to get permission.",
      ],
    },
  },
  {
    text: "advertise on Reddit",
    action: {
      type: "show-details",
      content: advertisingDetails,
    },
  },
  {
    text: "make a press inquiry",
    action: {
      type: "show-details",
      content: pressDetails,
    },
  },  
  {
      text: "question about Reddit gold",
      action: {
        type: "show-details",
        content: [
          "Got a question about " +
          link({url: getRedditURL("/gold/about"), text: "Reddit gold"}) +
          "? Please email " +
          link({url: "mailto:goldsupport@reddit.com", text: "goldsupport@reddit.com"}) +
          ".",
        ],
      },
  },
  {
    text: "message the admins",
    action: {
      type: "show-form",
      content: contactAdminsForm,
    }
  }],
}



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

function initContactPage(firstForm) {
  showForm(firstForm);
  setupDetailsListeners();
}


initContactPage(contactForm);
