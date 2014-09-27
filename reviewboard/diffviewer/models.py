from __future__ import unicode_literals

import bz2
import logging

from django.db import models
from django.db.models import Q
from django.utils import six, timezone
from django.utils.encoding import python_2_unicode_compatible
from django.utils.translation import ugettext_lazy as _
from djblets.db.fields import Base64Field, JSONField

from reviewboard.diffviewer.errors import DiffParserError
from reviewboard.diffviewer.managers import (RawFileDiffDataManager,
                                             FileDiffManager,
                                             DiffSetManager)
from reviewboard.scmtools.core import PRE_CREATION
from reviewboard.scmtools.models import Repository


class LegacyFileDiffData(models.Model):
    """Deprecated, legacy class for base64-encoded diff data.

    This is no longer populated, and exists solely to store legacy data
    that has not been migrated to RawFileDiffData.
    """
    binary_hash = models.CharField(_("hash"), max_length=40, primary_key=True)
    binary = Base64Field(_("base64"))

    extra_data = JSONField(null=True)

    class Meta:
        db_table = 'diffviewer_filediffdata'


class RawFileDiffData(models.Model):
    """Stores raw diff data as binary content in the database.

    This is the class used in Review Board 2.1+ to store diff content.
    Unlike in previous versions, the content is not base64-encoded. Instead,
    it is stored either as bzip2-compressed data (if the resulting
    compressed data is smaller than the raw data), or as the raw data itself.
    """
    COMPRESSION_BZIP2 = 'B'

    COMPRESSION_CHOICES = (
        (COMPRESSION_BZIP2, _('BZip2-compressed')),
    )

    binary_hash = models.CharField(_("hash"), max_length=40, unique=True)
    binary = models.BinaryField()
    compression = models.CharField(max_length=1, choices=COMPRESSION_CHOICES,
                                   null=True, blank=True)
    extra_data = JSONField(null=True)

    objects = RawFileDiffDataManager()

    @property
    def content(self):
        """Returns the content of the diff.

        The content will be uncompressed (if necessary) and returned as the
        raw set of bytes originally uploaded.
        """
        if self.compression == self.COMPRESSION_BZIP2:
            return bz2.decompress(self.binary)
        elif self.compression is None:
            return bytes(self.binary)
        else:
            raise NotImplementedError(
                'Unsupported compression method %s for RawFileDiffData %s'
                % (self.compression, self.pk))

    @property
    def insert_count(self):
        return self.extra_data.get('insert_count')

    @insert_count.setter
    def insert_count(self, value):
        self.extra_data['insert_count'] = value

    @property
    def delete_count(self):
        return self.extra_data.get('delete_count')

    @delete_count.setter
    def delete_count(self, value):
        self.extra_data['delete_count'] = value

    def recalculate_line_counts(self, tool):
        """Recalculates the insert_count and delete_count values.

        This will attempt to re-parse the stored diff and fetch the
        line counts through the parser.
        """
        logging.debug('Recalculating insert/delete line counts on '
                      'RawFileDiffData %s' % self.pk)

        try:
            files = tool.get_parser(self.content).parse()

            if len(files) != 1:
                raise DiffParserError(
                    'Got wrong number of files (%d)' % len(files))
        except DiffParserError as e:
            logging.error('Failed to correctly parse stored diff data in '
                          'RawFileDiffData ID %s when trying to get '
                          'insert/delete line counts: %s',
                          self.pk, e)
        else:
            file_info = files[0]
            self.insert_count = file_info.insert_count
            self.delete_count = file_info.delete_count

            if self.pk:
                self.save(update_fields=['extra_data'])


@python_2_unicode_compatible
class FileDiff(models.Model):
    """
    A diff of a single file.

    This contains the patch and information needed to produce original and
    patched versions of a single file in a repository.
    """
    COPIED = 'C'
    DELETED = 'D'
    MODIFIED = 'M'
    MOVED = 'V'

    STATUSES = (
        (COPIED, _('Copied')),
        (DELETED, _('Deleted')),
        (MODIFIED, _('Modified')),
        (MOVED, _('Moved')),
    )

    diffset = models.ForeignKey('DiffSet',
                                related_name='files',
                                verbose_name=_("diff set"))

    source_file = models.CharField(_("source file"), max_length=1024)
    dest_file = models.CharField(_("destination file"), max_length=1024)
    source_revision = models.CharField(_("source file revision"),
                                       max_length=512)
    dest_detail = models.CharField(_("destination file details"),
                                   max_length=512)
    binary = models.BooleanField(_("binary file"), default=False)
    status = models.CharField(_("status"), max_length=1, choices=STATUSES)

    diff64 = Base64Field(
        _("diff"),
        db_column="diff_base64",
        blank=True)
    legacy_diff_hash = models.ForeignKey(
        LegacyFileDiffData,
        db_column='diff_hash_id',
        related_name='filediffs',
        null=True,
        blank=True)
    diff_hash = models.ForeignKey(
        RawFileDiffData,
        db_column='raw_diff_hash_id',
        related_name='filediffs',
        null=True,
        blank=True)

    parent_diff64 = Base64Field(
        _("parent diff"),
        db_column="parent_diff_base64",
        blank=True)
    legacy_parent_diff_hash = models.ForeignKey(
        LegacyFileDiffData,
        db_column='parent_diff_hash_id',
        related_name='parent_filediffs',
        null=True,
        blank=True)
    parent_diff_hash = models.ForeignKey(
        RawFileDiffData,
        db_column='raw_parent_diff_hash_id',
        related_name='parent_filediffs',
        null=True,
        blank=True)

    extra_data = JSONField(null=True)

    objects = FileDiffManager()

    @property
    def source_file_display(self):
        tool = self.diffset.repository.get_scmtool()
        return tool.normalize_path_for_display(self.source_file)

    @property
    def dest_file_display(self):
        tool = self.diffset.repository.get_scmtool()
        return tool.normalize_path_for_display(self.dest_file)

    @property
    def deleted(self):
        return self.status == self.DELETED

    @property
    def copied(self):
        return self.status == self.COPIED

    @property
    def moved(self):
        return self.status == self.MOVED

    @property
    def is_new(self):
        return self.source_revision == PRE_CREATION

    def _get_diff(self):
        if self._needs_diff_migration():
            self._migrate_diff_data()

        return self.diff_hash.content

    def _set_diff(self, diff):
        # Add hash to table if it doesn't exist, and set diff_hash to this.
        self.diff_hash, is_new = \
            RawFileDiffData.objects.get_or_create_from_data(diff)
        self.diff64 = ""

        return is_new

    diff = property(_get_diff, _set_diff)

    def _get_parent_diff(self):
        if self._needs_parent_diff_migration():
            self._migrate_diff_data()

        if self.parent_diff_hash:
            return self.parent_diff_hash.content
        else:
            return None

    def _set_parent_diff(self, parent_diff):
        if not parent_diff:
            return False

        # Add hash to table if it doesn't exist, and set diff_hash to this.
        self.parent_diff_hash, is_new = \
            RawFileDiffData.objects.get_or_create_from_data(parent_diff)
        self.parent_diff64 = ""

        return is_new

    parent_diff = property(_get_parent_diff, _set_parent_diff)

    def get_line_counts(self):
        """Returns the stored line counts for the diff.

        This will return all the types of line counts that can be set:

        * ``raw_insert_count``
        * ``raw_delete_count``
        * ``insert_count``
        * ``delete_count``
        * ``replace_count``
        * ``equal_count``
        * ``total_line_count``

        These are not all guaranteed to have values set, and may instead be
        None. Only ``raw_insert_count``, ``raw_delete_count``
        ``insert_count``, and ``delete_count`` are guaranteed to have values
        set.

        If there isn't a processed number of inserts or deletes stored,
        then ``insert_count`` and ``delete_count`` will be equal to the
        raw versions.
        """
        if ('raw_insert_count' not in self.extra_data or
            'raw_delete_count' not in self.extra_data):
            if not self.diff_hash:
                self._migrate_diff_data()

            if self.diff_hash.insert_count is None:
                self._recalculate_line_counts(self.diff_hash)

            self.extra_data.update({
                'raw_insert_count': self.diff_hash.insert_count,
                'raw_delete_count': self.diff_hash.delete_count,
            })

            if self.pk:
                self.save(update_fields=['extra_data'])

        raw_insert_count = self.extra_data['raw_insert_count']
        raw_delete_count = self.extra_data['raw_delete_count']

        return {
            'raw_insert_count': raw_insert_count,
            'raw_delete_count': raw_delete_count,
            'insert_count': self.extra_data.get('insert_count',
                                                raw_insert_count),
            'delete_count': self.extra_data.get('delete_count',
                                                raw_delete_count),
            'replace_count': self.extra_data.get('replace_count'),
            'equal_count': self.extra_data.get('equal_count'),
            'total_line_count': self.extra_data.get('total_line_count'),
        }

    def set_line_counts(self, raw_insert_count=None, raw_delete_count=None,
                        insert_count=None, delete_count=None,
                        replace_count=None, equal_count=None,
                        total_line_count=None):
        """Sets the line counts on the FileDiff.

        There are many types of useful line counts that can be set.

        ``raw_insert_count`` and ``raw_delete_count`` correspond to the
        raw inserts and deletes in the actual patch, which will be set both
        in this FileDiff and in the associated RawFileDiffData.

        The other counts are stored exclusively in FileDiff, as they are
        more render-specific.
        """
        updated = False

        if not self.diff_hash_id:
            # This really shouldn't happen, but if it does, we should handle
            # it gracefully.
            logging.warning('Attempting to call set_line_counts on '
                            'un-migrated FileDiff %s' % self.pk)
            self._migrate_diff_data(False)

        if (insert_count is not None and
            raw_insert_count is not None and
            self.diff_hash.insert_count is not None and
            self.diff_hash.insert_count != insert_count):
            # Allow overriding, but warn. This really shouldn't be called.
            logging.warning('Attempting to override insert count on '
                            'RawFileDiffData %s from %s to %s (FileDiff %s)'
                            % (self.diff_hash.pk,
                               self.diff_hash.insert_count,
                               insert_count,
                               self.pk))

        if (delete_count is not None and
            raw_delete_count is not None and
            self.diff_hash.delete_count is not None and
            self.diff_hash.delete_count != delete_count):
            # Allow overriding, but warn. This really shouldn't be called.
            logging.warning('Attempting to override delete count on '
                            'RawFileDiffData %s from %s to %s (FileDiff %s)'
                            % (self.diff_hash.pk,
                               self.diff_hash.delete_count,
                               delete_count,
                               self.pk))

        if raw_insert_count is not None or raw_delete_count is not None:
            # New raw counts have been provided. These apply to the actual
            # diff file itself, and will be common across all diffs sharing
            # the diff_hash instance. Set it there.
            if raw_insert_count is not None:
                self.diff_hash.insert_count = raw_insert_count
                self.extra_data['raw_insert_count'] = raw_insert_count
                updated = True

            if raw_delete_count is not None:
                self.diff_hash.delete_count = raw_delete_count
                self.extra_data['raw_delete_count'] = raw_delete_count
                updated = True

            self.diff_hash.save()

        for key, cur_value in (('insert_count', insert_count),
                               ('delete_count', delete_count),
                               ('replace_count', replace_count),
                               ('equal_count', equal_count),
                               ('total_line_count', total_line_count)):
            if cur_value is not None and cur_value != self.extra_data.get(key):
                self.extra_data[key] = cur_value
                updated = True

        if updated and self.pk:
            self.save(update_fields=['extra_data'])

    def _needs_diff_migration(self):
        return self.diff_hash_id is None

    def _needs_parent_diff_migration(self):
        return (self.parent_diff_hash_id is None and
                (self.parent_diff64 or self.legacy_parent_diff_hash_id))

    def _migrate_diff_data(self, recalculate_counts=True):
        """Migrates diff data associated with a FileDiff to RawFileDiffData.

        If the diff data is stored directly on the FileDiff, it will be
        removed and stored on a RawFileDiffData instead.

        If the diff data is stored on an associated LegacyFileDiffData,
        that will be converted into a RawFileDiffData. The LegacyFileDiffData
        will then be removed, if nothing else is using it.
        """
        needs_save = False
        diff_hash_is_new = False
        parent_diff_hash_is_new = False
        legacy_pks = []

        if self._needs_diff_migration():
            needs_save = True

            if self.legacy_diff_hash_id:
                logging.debug('Migrating LegacyFileDiffData %s to '
                              'RawFileDiffData for diff in FileDiff %s',
                              self.legacy_diff_hash_id, self.pk)

                diff_hash_is_new = self._set_diff(self.legacy_diff_hash.binary)
                legacy_pks.append(self.legacy_diff_hash_id)
                self.legacy_diff_hash = None
            else:
                logging.debug('Migrating FileDiff %s diff data to '
                              'RawFileDiffData',
                              self.pk)

                diff_hash_is_new = self._set_diff(self.diff64)

            if recalculate_counts:
                self._recalculate_line_counts(self.diff_hash)

        if self._needs_parent_diff_migration():
            needs_save = True

            if self.legacy_parent_diff_hash_id:
                logging.debug('Migrating LegacyFileDiffData %s to '
                              'RawFileDiffData for parent diff in FileDiff %s',
                              self.legacy_parent_diff_hash_id, self.pk)

                parent_diff_hash_is_new = \
                    self._set_parent_diff(self.legacy_parent_diff_hash.binary)
                legacy_pks.append(self.legacy_parent_diff_hash_id)
                self.legacy_parent_diff_hash = None
            else:
                logging.debug('Migrating FileDiff %s parent diff data to '
                              'RawFileDiffData',
                              self.pk)

                parent_diff_hash_is_new = \
                    self._set_parent_diff(self.parent_diff64)

            if recalculate_counts:
                self._recalculate_line_counts(self.parent_diff_hash)

        if needs_save:
            self.save()

        if legacy_pks:
            # Delete any LegacyFileDiffData objects no longer associated
            # with any FileDiffs.
            LegacyFileDiffData.objects \
                .filter(pk__in=legacy_pks) \
                .exclude(Q(filediffs__pk__gt=0) |
                         Q(parent_filediffs__pk__gt=0)) \
                .delete()

        return diff_hash_is_new, parent_diff_hash_is_new

    def _recalculate_line_counts(self, diff_hash):
        """Recalculates the line counts on the specified RawFileDiffData.

        This requires that diff_hash is set. Otherwise, it will assert.
        """
        diff_hash.recalculate_line_counts(
            self.diffset.repository.get_scmtool())

    def __str__(self):
        return "%s (%s) -> %s (%s)" % (self.source_file, self.source_revision,
                                       self.dest_file, self.dest_detail)


@python_2_unicode_compatible
class DiffSet(models.Model):
    """
    A revisioned collection of FileDiffs.
    """
    name = models.CharField(_('name'), max_length=256)
    revision = models.IntegerField(_("revision"))
    timestamp = models.DateTimeField(_("timestamp"), default=timezone.now)
    basedir = models.CharField(_('base directory'), max_length=256,
                               blank=True, default='')
    history = models.ForeignKey('DiffSetHistory', null=True,
                                related_name="diffsets",
                                verbose_name=_("diff set history"))
    repository = models.ForeignKey(Repository, related_name="diffsets",
                                   verbose_name=_("repository"))
    diffcompat = models.IntegerField(
        _('differ compatibility version'),
        default=0,
        help_text=_("The diff generator compatibility version to use. "
                    "This can and should be ignored."))

    base_commit_id = models.CharField(
        _('commit ID'), max_length=64, blank=True, null=True, db_index=True,
        help_text=_('The ID/revision this change is built upon.'))

    extra_data = JSONField(null=True)

    objects = DiffSetManager()

    def get_total_line_counts(self):
        """Returns the total line counts from all files in this diffset."""
        counts = {}

        for filediff in self.files.all():
            for key, value in six.iteritems(filediff.get_line_counts()):
                if counts.get(key) is None:
                    counts[key] = value
                elif value is not None:
                    counts[key] += value

        return counts

    def save(self, **kwargs):
        """
        Saves this diffset.

        This will set an initial revision of 1 if this is the first diffset
        in the history, and will set it to on more than the most recent
        diffset otherwise.
        """
        if self.revision == 0 and self.history is not None:
            if self.history.diffsets.count() == 0:
                # Start on revision 1. It's more human-grokable.
                self.revision = 1
            else:
                self.revision = self.history.diffsets.latest().revision + 1

        if self.history:
            self.history.last_diff_updated = self.timestamp
            self.history.save()

        super(DiffSet, self).save()

    def __str__(self):
        return "[%s] %s r%s" % (self.id, self.name, self.revision)

    class Meta:
        get_latest_by = 'revision'
        ordering = ['revision', 'timestamp']


@python_2_unicode_compatible
class DiffSetHistory(models.Model):
    """
    A collection of diffsets.

    This gives us a way to store and keep track of multiple revisions of
    diffsets belonging to an object.
    """
    name = models.CharField(_('name'), max_length=256)
    timestamp = models.DateTimeField(_("timestamp"), default=timezone.now)
    last_diff_updated = models.DateTimeField(
        _("last updated"),
        blank=True,
        null=True,
        default=None)

    extra_data = JSONField(null=True)

    def __str__(self):
        return 'Diff Set History (%s revisions)' % self.diffsets.count()

    class Meta:
        verbose_name_plural = "Diff set histories"
