from __future__ import unicode_literals

import json
import logging

from django import template
from django.db.models import Q
from django.template import TemplateSyntaxError
from django.template.defaultfilters import stringfilter
from django.template.loader import render_to_string
from django.utils import six
from django.utils.html import escape
from django.utils.translation import ugettext_lazy as _
from djblets.util.decorators import basictag, blocktag
from djblets.util.humanize import humanize_list

from reviewboard.accounts.models import Profile, Trophy
from reviewboard.reviews.fields import (get_review_request_fieldset,
                                        get_review_request_fieldsets)
from reviewboard.reviews.markdown_utils import markdown_escape
from reviewboard.reviews.models import (BaseComment, Group,
                                        ReviewRequest, ScreenshotComment,
                                        FileAttachmentComment)


register = template.Library()


@register.tag
@basictag(takes_context=False)
def display_review_request_trophies(review_request):
    """Returns the HTML for the trophies awarded to a review request."""
    trophy_models = Trophy.objects.get_trophies(review_request)

    if not trophy_models:
        return ''

    trophies = []
    for trophy_model in trophy_models:
        try:
            trophy_type_cls = trophy_model.trophy_type
            trophy_type = trophy_type_cls()
            trophies.append({
                'image_url': trophy_type.image_url,
                'image_width': trophy_type.image_width,
                'image_height': trophy_type.image_height,
                'text': trophy_type.get_display_text(trophy_model),
            })
        except Exception as e:
            logging.error('Error when rendering trophy %r (%r): %s',
                          trophy_model.pk, trophy_type_cls, e,
                          exc_info=1)

    return render_to_string('reviews/trophy_box.html', {'trophies': trophies})


@register.tag
@blocktag
def ifneatnumber(context, nodelist, rid):
    """
    Returns whether or not the specified number is a "neat" number.
    This is a number with a special property, such as being a
    palindrome or having trailing zeroes.

    If the number is a neat number, the contained content is rendered,
    and two variables, ``milestone`` and ``palindrome`` are defined.
    """
    if rid is None or rid < 1000:
        return ""

    ridstr = six.text_type(rid)
    interesting = False

    context.push()
    context['milestone'] = False
    context['palindrome'] = False

    if rid >= 1000:
        trailing = ridstr[1:]
        if trailing == "0" * len(trailing):
            context['milestone'] = True
            interesting = True

    if not interesting:
        if ridstr == ''.join(reversed(ridstr)):
            context['palindrome'] = True
            interesting = True

    if not interesting:
        context.pop()
        return ""

    s = nodelist.render(context)
    context.pop()
    return s


@register.tag
@basictag(takes_context=True)
def file_attachment_comments(context, file_attachment):
    """Returns a JSON array of current comments for a file attachment."""
    comments = []
    user = context.get('user', None)

    for comment in file_attachment.get_comments():
        review = comment.get_review()

        if review and (review.public or review.user == user):
            comments.append({
                'comment_id': comment.id,
                'text': escape(comment.text),
                'user': {
                    'username': escape(review.user.username),
                    'name': escape(review.user.get_full_name() or
                                   review.user.username),
                },
                'url': comment.get_review_url(),
                'localdraft': review.user == user and not review.public,
                'review_id': review.id,
                'issue_opened': comment.issue_opened,
                'issue_status': escape(
                    BaseComment.issue_status_to_string(comment.issue_status)),
            })

    return json.dumps(comments)


@register.tag
@basictag(takes_context=True)
def reply_list(context, entry, comment, context_type, context_id):
    """
    Renders a list of comments of a specified type.

    This is a complex, confusing function accepts lots of inputs in order
    to display replies to a type of object. In each case, the replies will
    be rendered using the template :template:`reviews/review_reply.html`.

    If ``context_type`` is ``"diff_comments"``, ``"screenshot_comments"``
    or ``"file_attachment_comments"``, the generated list of replies are to
    ``comment``.

    If ``context_type`` is ``"body_top"`` or ```"body_bottom"``,
    the generated list of replies are to ``review``. Depending on the
    ``context_type``, these will either be replies to the top of the
    review body or to the bottom.

    The ``context_id`` parameter has to do with the internal IDs used by
    the JavaScript code for storing and categorizing the comments.
    """
    def generate_reply_html(reply, timestamp, text, rich_text,
                            comment_id=None):
        new_context = context
        new_context.update({
            'context_id': context_id,
            'id': reply.id,
            'review': review,
            'timestamp': timestamp,
            'text': text,
            'reply_user': reply.user,
            'draft': not reply.public,
            'comment_id': comment_id,
            'rich_text': rich_text,
        })
        return render_to_string('reviews/review_reply.html', new_context)

    def process_body_replies(queryset, attrname, user):
        if user.is_anonymous():
            queryset = queryset.filter(public=True)
        else:
            queryset = queryset.filter(Q(public=True) | Q(user=user))

        s = ""
        for reply_comment in queryset:
            s += generate_reply_html(reply, reply.timestamp,
                                     getattr(reply, attrname))

        return s

    review = entry['review']

    user = context.get('user', None)
    if user.is_anonymous():
        user = None

    s = ""

    if context_type in ('diff_comments', 'screenshot_comments',
                        'file_attachment_comments'):
        for reply_comment in comment.public_replies(user):
            s += generate_reply_html(reply_comment.get_review(),
                                     reply_comment.timestamp,
                                     reply_comment.text,
                                     reply_comment.rich_text,
                                     reply_comment.pk)
    elif context_type == "body_top" or context_type == "body_bottom":
        replies = getattr(review, "public_%s_replies" % context_type)()

        for reply in replies:
            s += generate_reply_html(reply, reply.timestamp,
                                     getattr(reply, context_type),
                                     reply.rich_text)

        return s
    else:
        raise TemplateSyntaxError("Invalid context type passed")

    return s


@register.inclusion_tag('reviews/review_reply_section.html',
                        takes_context=True)
def reply_section(context, entry, comment, context_type, context_id):
    """
    Renders a template for displaying a reply.

    This takes the same parameters as :tag:`reply_list`. The template
    rendered by this function, :template:`reviews/review_reply_section.html`,
    is responsible for invoking :tag:`reply_list` and as such passes these
    variables through. It does not make use of them itself.
    """
    if comment != "":
        if type(comment) is ScreenshotComment:
            context_id += 's'
        elif type(comment) is FileAttachmentComment:
            context_id += 'f'

        context_id += six.text_type(comment.id)

    return {
        'entry': entry,
        'comment': comment,
        'context_type': context_type,
        'context_id': context_id,
        'user': context.get('user', None),
        'local_site_name': context.get('local_site_name'),
    }


@register.inclusion_tag('datagrids/dashboard_entry.html', takes_context=True)
def dashboard_entry(context, level, text, view, param=None):
    """
    Renders an entry in the dashboard sidebar.

    This includes the name of the entry and the list of review requests
    associated with it. The entry is rendered by the template
    :template:`datagrids/dashboard_entry.html`.
    """
    user = context.get('user', None)
    sidebar_counts = context.get('sidebar_counts', None)
    starred = False
    show_count = True
    count = 0
    url = None
    group_name = None

    if view == 'to-group':
        group_name = param
        count = sidebar_counts['groups'].get(
            group_name,
            sidebar_counts['starred_groups'].get(group_name, 0))
    elif view == 'watched-groups':
        starred = True
        show_count = False
    elif view in sidebar_counts:
        count = sidebar_counts[view]

        if view == 'starred':
            starred = True
    elif view == "url":
        url = param
        show_count = False
    else:
        raise template.TemplateSyntaxError(
            "Invalid view type '%s' passed to 'dashboard_entry' tag." % view)

    return {
        'level': level,
        'text': text,
        'view': view,
        'group_name': group_name,
        'url': url,
        'count': count,
        'show_count': show_count,
        'user': user,
        'starred': starred,
        'selected': (context.get('view', None) == view and
                     (not group_name or
                      context.get('group', None) == group_name)),
        'local_site_name': context.get('local_site_name'),
    }


@register.simple_tag
def reviewer_list(review_request):
    """
    Returns a humanized list of target reviewers in a review request.
    """
    return humanize_list([group.display_name or group.name
                          for group in review_request.target_groups.all()] +
                         [user.get_full_name() or user.username
                          for user in review_request.target_people.all()])


@register.tag
@blocktag(end_prefix='end_')
def for_review_request_field(context, nodelist, review_request_details,
                             fieldset):
    """Loops through all fields in a fieldset.

    This can take a fieldset instance or a fieldset ID.
    """
    s = []

    if isinstance(fieldset, six.text_type):
        fieldset = get_review_request_fieldset(fieldset)

    for field_cls in fieldset.field_classes:
        try:
            field = field_cls(review_request_details)
        except Exception as e:
            logging.error('Error instantiating ReviewRequestFieldset %r: %s',
                          field_cls, e, exc_info=1)

        try:
            if field.should_render(field.value):
                context.push()
                context['field'] = field
                s.append(nodelist.render(context))
                context.pop()
        except Exception as e:
            logging.error('Error running should_render for '
                          'ReviewRequestFieldset %r: %s', field_cls, e,
                          exc_info=1)

    return ''.join(s)


@register.tag
@blocktag(end_prefix='end_')
def for_review_request_fieldset(context, nodelist, review_request_details):
    """Loops through all fieldsets.

    This skips the "main" fieldset, as that's handled separately by the
    template.
    """
    s = []
    is_first = True
    review_request = review_request_details.get_review_request()
    user = context['request'].user
    fieldset_classes = get_review_request_fieldsets(include_main=False)

    for fieldset_cls in fieldset_classes:
        try:
            if not fieldset_cls.is_empty():
                try:
                    fieldset = fieldset_cls(review_request_details)
                except Exception as e:
                    logging.error('Error instantiating ReviewRequestFieldset '
                                  '%r: %s', fieldset_cls, e, exc_info=1)

                context.push()
                context.update({
                    'fieldset': fieldset,
                    'show_fieldset_required': (
                        fieldset.show_required and
                        review_request.status == ReviewRequest.PENDING_REVIEW and
                        review_request.is_mutable_by(user)),
                    'forloop': {
                        'first': is_first,
                        }
                })
                s.append(nodelist.render(context))
                context.pop()

                is_first = False
        except Exception as e:
            logging.error('Error running is_empty for ReviewRequestFieldset '
                          '%r: %s', fieldset_cls, e, exc_info=1)

    return ''.join(s)


@register.assignment_tag
def has_usable_review_ui(user, review_request, file_attachment):
    """Returns whether a review UI is set and can be used."""
    review_ui = file_attachment.review_ui

    return (review_ui and
            review_ui.is_enabled_for(user=user,
                                     review_request=review_request,
                                     file_attachment=file_attachment))


@register.filter
def bug_url(bug_id, review_request):
    """
    Returns the URL based on a bug number on the specified review request.

    If the repository the review request belongs to doesn't have an
    associated bug tracker, this returns None.
    """
    if (review_request.repository and
        review_request.repository.bug_tracker and
        '%s' in review_request.repository.bug_tracker):
        try:
            return review_request.repository.bug_tracker % bug_id
        except TypeError:
            logging.error("Error creating bug URL. The bug tracker URL '%s' "
                          "is likely invalid." %
                          review_request.repository.bug_tracker)

    return None


@register.tag
@basictag(takes_context=True)
def star(context, obj):
    """
    Renders the code for displaying a star used for starring items.

    The rendered code should handle click events so that the user can
    toggle the star. The star is rendered by the template
    :template:`reviews/star.html`.

    The passed object must be either a :model:`reviews.ReviewRequest` or
    a :model:`reviews.Group`.
    """
    return render_star(context.get('user', None), obj)


def render_star(user, obj):
    """
    Does the actual work of rendering the star. The star tag is a wrapper
    around this.
    """
    if user.is_anonymous():
        return ""

    profile = None

    if not hasattr(obj, 'starred'):
        try:
            profile = user.get_profile()
        except Profile.DoesNotExist:
            return ""

    if isinstance(obj, ReviewRequest):
        obj_info = {
            'type': 'reviewrequests',
            'id': obj.display_id
        }

        if hasattr(obj, 'starred'):
            starred = obj.starred
        else:
            starred = \
                profile.starred_review_requests.filter(pk=obj.id).count() > 0
    elif isinstance(obj, Group):
        obj_info = {
            'type': 'groups',
            'id': obj.name
        }

        if hasattr(obj, 'starred'):
            starred = obj.starred
        else:
            starred = \
                profile.starred_groups.filter(pk=obj.id).count() > 0
    else:
        raise template.TemplateSyntaxError(
            "star tag received an incompatible object type (%s)" %
            type(obj))

    if starred:
        image_alt = _("Starred")
    else:
        image_alt = _("Click to star")

    return render_to_string('reviews/star.html', {
        'object': obj_info,
        'starred': int(starred),
        'alt': image_alt,
        'user': user,
    })


@register.inclusion_tag('reviews/comment_issue.html',
                        takes_context=True)
def comment_issue(context, review_request, comment, comment_type):
    """
    Renders the code responsible for handling comment issue statuses.
    """

    issue_status = BaseComment.issue_status_to_string(comment.issue_status)
    user = context.get('user', None)

    return {
        'comment': comment,
        'comment_type': comment_type,
        'issue_status': issue_status,
        'review': comment.get_review(),
        'interactive': comment.can_change_issue_status(user),
    }


@register.filter
@stringfilter
def pretty_print_issue_status(status):
    """Turns an issue status code into a human-readable status string."""
    return BaseComment.issue_status_to_string(status)


@register.filter('markdown_escape')
def markdown_escape_filter(text, is_rich_text):
    """Returns Markdown text, escaping if necessary.

    If ``is_rich_text`` is ``True``, then the provided text will be
    returned directly. Otherwise, it will first be escaped and then returned.
    """
    if is_rich_text:
        return text
    else:
        return markdown_escape(text)
