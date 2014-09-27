from __future__ import unicode_literals

from django.utils import six
from djblets.webapi.errors import DOES_NOT_EXIST

from reviewboard.scmtools.core import PRE_CREATION
from reviewboard.webapi.resources import resources
from reviewboard.webapi.tests.base import BaseWebAPITestCase
from reviewboard.webapi.tests.mimetypes import original_file_mimetype
from reviewboard.webapi.tests.mixins import (BasicTestsMetaclass,
                                             ReviewRequestChildItemMixin)
from reviewboard.webapi.tests.urls import get_original_file_url


@six.add_metaclass(BasicTestsMetaclass)
class ResourceTests(ReviewRequestChildItemMixin, BaseWebAPITestCase):
    """Testing the OriginalFileResource APIs."""
    fixtures = ['test_users', 'test_scmtools']
    sample_api_url = \
        'review-requests/<id>/diffs/<id>/files/<id>/original-file/'
    resource = resources.original_file
    basic_get_returns_json = False

    def setup_review_request_child_test(self, review_request):
        if not review_request.repository:
            repository = self.create_repository(public=False, tool_name='Test')
            repository.users.add(self.user)
            review_request.repository = repository
            review_request.save()

        diffset = self.create_diffset(review_request)
        filediff = self.create_filediff(diffset)

        return (get_original_file_url(review_request, diffset, filediff),
                original_file_mimetype)

    def setup_http_not_allowed_list_test(self, user):
        repository = self.create_repository(tool_name='Test')
        review_request = self.create_review_request(
            repository=repository,
            submitter=user,
            publish=True)
        diffset = self.create_diffset(review_request)
        filediff = self.create_filediff(diffset)

        return get_original_file_url(review_request, diffset, filediff)

    setup_http_not_allowed_item_test = setup_http_not_allowed_list_test

    def compare_item(self, data, filediff):
        self.assertEqual(data, 'Hello, world!\n')

    #
    # HTTP GET tests
    #

    def setup_basic_get_test(self, user, with_local_site, local_site_name):
        repository = self.create_repository(tool_name='Test')
        review_request = self.create_review_request(
            repository=repository,
            with_local_site=with_local_site,
            submitter=user,
            publish=True)
        diffset = self.create_diffset(review_request)
        filediff = self.create_filediff(diffset)

        return (get_original_file_url(review_request, diffset, filediff,
                                      local_site_name=local_site_name),
                original_file_mimetype,
                filediff)

    def test_with_new_file(self):
        """Testing the
        GET review-requests/<id>/diffs/<id>/files/<id>/original-file/ API
        with new file
        """
        repository = self.create_repository(tool_name='Test')
        review_request = self.create_review_request(
            repository=repository,
            submitter=self.user,
            publish=True)
        diffset = self.create_diffset(review_request)
        filediff = self.create_filediff(diffset, source_revision=PRE_CREATION)

        rsp = self.api_get(
            get_original_file_url(review_request, diffset, filediff),
            expected_status=404)
        self.assertEqual(rsp['stat'], 'fail')
        self.assertEqual(rsp['err']['code'], DOES_NOT_EXIST.code)

    def test_with_draft_diff(self):
        """Testing the
        GET review-requests/<id>/diffs/<id>/files/<id>/original-file/ API
        with draft diff
        """
        repository = self.create_repository(tool_name='Test')
        review_request = self.create_review_request(
            repository=repository,
            submitter=self.user,
            publish=True)
        diffset = self.create_diffset(review_request, draft=True)
        filediff = self.create_filediff(diffset)

        rsp = self.api_get(
            get_original_file_url(review_request, diffset, filediff),
            expected_status=404)
        self.assertEqual(rsp['stat'], 'fail')
        self.assertEqual(rsp['err']['code'], DOES_NOT_EXIST.code)
