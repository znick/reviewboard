/*
 * The draft of a review request.
 *
 * This provides editing capabilities for a review request draft, as well
 * as the ability to publish and discard (destroy) a draft.
 */
RB.DraftReviewRequest = RB.BaseResource.extend(_.defaults({
    defaults: _.defaults({
        branch: null,
        bugsClosed: null,
        changeDescription: null,
        dependsOn: [],
        description: null,
        'public': null,
        richText: false,
        summary: null,
        targetGroups: [],
        targetPeople: [],
        testingDone: null
    }, RB.BaseResource.prototype.defaults),

    rspNamespace: 'draft',
    listKey: 'draft',
    supportsExtraData: true,

    expandedFields: ['depends_on', 'target_people', 'target_groups'],

    extraQueryArgs: {
        'force-text-type': 'markdown'
    },

    url: function() {
        return this.get('parentObject').get('links').draft.href;
    },

    /*
     * Creates a FileAttachment object for this draft.
     */
    createFileAttachment: function(attributes) {
        return new RB.DraftFileAttachment(_.defaults({
            parentObject: this
        }, attributes));
    },

    /*
     * Publishes the draft.
     *
     * The contents of the draft will be validated before being sent to the
     * server in order to ensure that the appropriate fields are all there.
     */
    publish: function(options, context) {
        options = options || {};

        this.ready({
            ready: function() {
                var validationError = this.validate(this.attributes, {
                    publishing: true
                });

                if (validationError) {
                    if (_.isFunction(options.error)) {
                        options.error.call(context, this, {
                            errorText: validationError
                        });
                    }
                } else {
                    this.save(
                        _.defaults({
                            data: {
                                'public': 1
                            }
                        }, options),
                        context);
                }
            },
            error: _.isFunction(options.error)
                   ? _.bind(options.error, context)
                   : undefined
        }, this);
    },

    validate: function(attrs, options) {
        var strings = RB.DraftReviewRequest.strings;

        if (options.publishing) {
            if (attrs.targetGroups.length === 0 &&
                attrs.targetPeople.length === 0) {
                return strings.REVIEWERS_REQUIRED;
            }

            if ($.trim(attrs.summary) === '') {
                return strings.SUMMARY_REQUIRED;
            }

            if ($.trim(attrs.description) === '') {
                return strings.DESCRIPTION_REQUIRED;
            }
        }

        return _super(this).validate.call(this, attrs, options);
    },

    parseResourceData: function(rsp) {
        return {
            branch: rsp.branch,
            bugsClosed: rsp.bugs_closed,
            changeDescription: rsp.changedescription,
            dependsOn: rsp.depends_on,
            description: rsp.description,
            'public': rsp['public'],
            richText: rsp.text_type === 'markdown',
            summary: rsp.summary,
            targetGroups: rsp.target_groups,
            targetPeople: rsp.target_people,
            testingDone: rsp.testing_done
        };
    }
}, RB.DraftResourceModelMixin),
{
    strings: {
        DESCRIPTION_REQUIRED: gettext('The draft must have a description.'),
        REVIEWERS_REQUIRED: gettext('There must be at least one reviewer before this review request can be published.'),
        SUMMARY_REQUIRED: gettext('The draft must have a summary.')
    }
});
