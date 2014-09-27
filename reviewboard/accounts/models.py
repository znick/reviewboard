from __future__ import unicode_literals

from django.contrib.auth.models import User
from django.db import models
from django.dispatch import receiver
from django.utils import timezone
from django.utils.encoding import python_2_unicode_compatible
from django.utils.functional import cached_property
from django.utils.translation import ugettext_lazy as _
from djblets.db.fields import CounterField, JSONField
from djblets.db.managers import ConcurrencyManager
from djblets.forms.fields import TIMEZONE_CHOICES

from reviewboard.accounts.managers import ProfileManager, TrophyManager
from reviewboard.accounts.trophies import TrophyType
from reviewboard.reviews.models import Group, ReviewRequest
from reviewboard.reviews.signals import review_request_published
from reviewboard.site.models import LocalSite


@python_2_unicode_compatible
class ReviewRequestVisit(models.Model):
    """
    A recording of the last time a review request was visited by a user.

    Users have one ReviewRequestVisit entry in the database per review
    request they've visited. This is used to keep track of any updates
    to review requests they've already seen, so that we can intelligently
    inform them that new discussions have taken place.
    """
    user = models.ForeignKey(User, related_name="review_request_visits")
    review_request = models.ForeignKey(ReviewRequest, related_name="visits")
    timestamp = models.DateTimeField(_('last visited'), default=timezone.now)

    # Set this up with a ConcurrencyManager to help prevent race conditions.
    objects = ConcurrencyManager()

    def __str__(self):
        return "Review request visit"

    class Meta:
        unique_together = ("user", "review_request")


@python_2_unicode_compatible
class Profile(models.Model):
    """User profile.  Contains some basic configurable settings"""
    user = models.ForeignKey(User, unique=True)

    # This will redirect new users to the account settings page the first time
    # they log in (or immediately after creating an account).  This allows
    # people to fix their real name and join groups.
    first_time_setup_done = models.BooleanField(
        default=False,
        verbose_name=_("first time setup done"),
        help_text=_("Indicates whether the user has already gone through "
                    "the first time setup process by saving their user "
                    "preferences."))

    # Whether the user wants to receive emails
    should_send_email = models.BooleanField(
        default=True,
        verbose_name=_("send email"),
        help_text=_("Indicates whether the user wishes to receive emails."))

    collapsed_diffs = models.BooleanField(
        default=True,
        verbose_name=_("collapsed diffs"),
        help_text=_("Indicates whether diffs should be shown in their "
                    "collapsed state by default."))
    wordwrapped_diffs = models.BooleanField(
        default=True,
        help_text=_("This field is unused and will be removed in a future "
                    "version."))
    syntax_highlighting = models.BooleanField(
        default=True,
        verbose_name=_("syntax highlighting"),
        help_text=_("Indicates whether the user wishes to see "
                    "syntax highlighting in the diffs."))
    is_private = models.BooleanField(
        default=False,
        verbose_name=_("profile private"),
        help_text=_("Indicates whether the user wishes to keep his/her "
                    "profile private."))
    open_an_issue = models.BooleanField(
        default=True,
        verbose_name=_("opens an issue"),
        help_text=_("Indicates whether the user wishes to default "
                    "to opening an issue or not."))

    # Indicate whether closed review requests should appear in the
    # review request lists (excluding the dashboard).
    show_closed = models.BooleanField(default=True)

    sort_review_request_columns = models.CharField(max_length=256, blank=True)
    sort_dashboard_columns = models.CharField(max_length=256, blank=True)
    sort_submitter_columns = models.CharField(max_length=256, blank=True)
    sort_group_columns = models.CharField(max_length=256, blank=True)

    review_request_columns = models.CharField(max_length=256, blank=True)
    dashboard_columns = models.CharField(max_length=256, blank=True)
    submitter_columns = models.CharField(max_length=256, blank=True)
    group_columns = models.CharField(max_length=256, blank=True)

    # A list of starred review requests. This allows users to monitor a
    # review request and receive e-mails on updates without actually being
    # on the reviewer list or commenting on the review. This is similar to
    # adding yourself to a CC list.
    starred_review_requests = models.ManyToManyField(ReviewRequest, blank=True,
                                                     related_name="starred_by")

    # A list of watched groups. This is so that users can monitor groups
    # without actually joining them, preventing e-mails being sent to the
    # user and review requests from entering the Incoming Reviews list.
    starred_groups = models.ManyToManyField(Group, blank=True,
                                            related_name="starred_by")

    # Allows per-user timezone settings
    timezone = models.CharField(choices=TIMEZONE_CHOICES, default='UTC',
                                max_length=30)

    extra_data = JSONField(null=True)

    objects = ProfileManager()

    def star_review_request(self, review_request):
        """Marks a review request as starred.

        This will mark a review request as starred for this user and
        immediately save to the database.
        """
        self.starred_review_requests.add(review_request)

        if (review_request.public and
            (review_request.status == ReviewRequest.PENDING_REVIEW or
             review_request.status == ReviewRequest.SUBMITTED)):
            site_profile, is_new = LocalSiteProfile.objects.get_or_create(
                user=self.user,
                local_site=review_request.local_site,
                profile=self)

            if is_new:
                site_profile.save()

            site_profile.increment_starred_public_request_count()

        self.save()

    def unstar_review_request(self, review_request):
        """Marks a review request as unstarred.

        This will mark a review request as starred for this user and
        immediately save to the database.
        """
        q = self.starred_review_requests.filter(pk=review_request.pk)

        if q.count() > 0:
            self.starred_review_requests.remove(review_request)

        if (review_request.public and
            (review_request.status == ReviewRequest.PENDING_REVIEW or
             review_request.status == ReviewRequest.SUBMITTED)):
            site_profile, is_new = LocalSiteProfile.objects.get_or_create(
                user=self.user,
                local_site=review_request.local_site,
                profile=self)

            if is_new:
                site_profile.save()

            site_profile.decrement_starred_public_request_count()

        self.save()

    def star_review_group(self, review_group):
        """Marks a review group as starred.

        This will mark a review group as starred for this user and
        immediately save to the database.
        """
        if self.starred_groups.filter(pk=review_group.pk).count() == 0:
            self.starred_groups.add(review_group)

    def unstar_review_group(self, review_group):
        """Marks a review group as unstarred.

        This will mark a review group as starred for this user and
        immediately save to the database.
        """
        if self.starred_groups.filter(pk=review_group.pk).count() > 0:
            self.starred_groups.remove(review_group)

    def __str__(self):
        return self.user.username


@python_2_unicode_compatible
class LocalSiteProfile(models.Model):
    """User profile information specific to a LocalSite."""
    user = models.ForeignKey(User, related_name='site_profiles')
    profile = models.ForeignKey(Profile, related_name='site_profiles')
    local_site = models.ForeignKey(LocalSite, null=True, blank=True,
                                   related_name='site_profiles')

    # A dictionary of permission that the user has granted. Any permission
    # missing is considered to be False.
    permissions = JSONField(null=True)

    # Counts for quickly knowing how many review requests are incoming
    # (both directly and total), outgoing (pending and total ever made),
    # and starred (public).
    direct_incoming_request_count = CounterField(
        _('direct incoming review request count'),
        initializer=lambda p: ReviewRequest.objects.to_user_directly(
            p.user, local_site=p.local_site).count())
    total_incoming_request_count = CounterField(
        _('total incoming review request count'),
        initializer=lambda p: ReviewRequest.objects.to_user(
            p.user, local_site=p.local_site).count())
    pending_outgoing_request_count = CounterField(
        _('pending outgoing review request count'),
        initializer=lambda p: ReviewRequest.objects.from_user(
            p.user, p.user, local_site=p.local_site).count())
    total_outgoing_request_count = CounterField(
        _('total outgoing review request count'),
        initializer=lambda p: ReviewRequest.objects.from_user(
            p.user, p.user, None, local_site=p.local_site).count())
    starred_public_request_count = CounterField(
        _('starred public review request count'),
        initializer=lambda p: (p.pk and
                               p.profile.starred_review_requests.public(
                                   user=None,
                                   local_site=p.local_site).count()) or 0)

    class Meta:
        unique_together = (('user', 'local_site'),
                           ('profile', 'local_site'))

    def __str__(self):
        return '%s (%s)' % (self.user.username, self.local_site)


class Trophy(models.Model):
    """A trophy represents an achievement given to the user.

    It is associated with a ReviewRequest and a User and can be associated
    with a LocalSite.
    """
    category = models.CharField(max_length=100)
    received_date = models.DateTimeField(default=timezone.now)
    review_request = models.ForeignKey(ReviewRequest, related_name="trophies")
    local_site = models.ForeignKey(LocalSite, null=True,
                                   related_name="trophies")
    user = models.ForeignKey(User, related_name="trophies")

    objects = TrophyManager()

    @cached_property
    def trophy_type(self):
        """Get the TrophyType instance for this trophy."""
        return TrophyType.for_category(self.category)

    def get_display_text(self):
        """Get the display text for this trophy."""
        return self.trophy_type.get_display_text(self)


#
# The following functions are patched onto the User model.
#

def _is_user_profile_visible(self, user=None):
    """Returns whether or not a User's profile is viewable by a given user.

    A profile is viewable if it's not marked as private, or the viewing
    user owns the profile, or the user is a staff member.
    """
    try:
        if hasattr(self, 'is_private'):
            # This is an optimization used by the web API. It will set
            # is_private on this User instance through a query, saving a
            # lookup for each instance.
            #
            # This must be done because select_related() and
            # prefetch_related() won't cache reverse foreign key relations.
            is_private = self.is_private
        else:
            is_private = self.get_profile().is_private

        return ((user and (user == self or user.is_staff)) or
                not is_private)
    except Profile.DoesNotExist:
        return True


def _should_send_email(self):
    """Returns whether a user wants to receive emails.

    This is patched into the user object to make it easier to deal with missing
    Profile objects."""
    try:
        return self.get_profile().should_send_email
    except Profile.DoesNotExist:
        return True


def _get_profile(self):
    """Returns the profile for the User.

    The profile will be cached, preventing queries for future lookups.
    """
    if not hasattr(self, '_profile'):
        self._profile = Profile.objects.get(user=self)
        self._profile.user = self

    return self._profile


def _get_site_profile(self, local_site):
    """Returns the LocalSiteProfile for a given LocalSite for the User.

    The profile will be cached, preventing queries for future lookups.
    """
    if not hasattr(self, '_site_profiles'):
        self._site_profiles = {}

    if local_site.pk not in self._site_profiles:
        site_profile = \
            LocalSiteProfile.objects.get(user=self, local_site=local_site)
        site_profile.user = self
        site_profile.local_site = local_site
        self._site_profiles[local_site.pk] = site_profile

    return self._site_profiles[local_site.pk]


User.is_profile_visible = _is_user_profile_visible
User.get_profile = _get_profile
User.get_site_profile = _get_site_profile
User.should_send_email = _should_send_email
User._meta.ordering = ('username',)


@receiver(review_request_published)
def _call_compute_trophies(sender, review_request, **kwargs):
    if review_request.changedescs.count() == 0 and review_request.public:
        Trophy.objects.compute_trophies(review_request)
