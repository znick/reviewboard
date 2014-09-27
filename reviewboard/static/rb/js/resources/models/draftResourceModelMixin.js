/*
 * Mixin for resources that have special "draft" URLs.
 *
 * Some resources contain a "draft/" singleton URL that will either redirect to
 * the URL for an existing draft, or indicate there's no draft (and requiring
 * that one be created).
 *
 * These resources need a little more logic to look up the draft state and
 * craft the proper URL. They can use this mixin to do that work for them.
 */
RB.DraftResourceModelMixin = {
    /*
     * Calls a function when the object is ready to use.
     *
     * If the object is unloaded, we'll likely need to grab the draft
     * resource, particularly if we haven't already retrieved a draft.
     *
     * Otherwise, we delegate to the parent's ready().
     */
    ready: function(options, context) {
        var self = this,
            sup = _super(this);

        if (!this.get('loaded') && this.isNew() &&
            this._needDraft === undefined) {
            this._needDraft = true;
        }

        if (this._needDraft) {
            /*
             * Start by delegating to the parent ready() function. Because the
             * object is "new", this will make sure that the parentObject is
             * ready.
             */
            sup.ready.call(
                this,
                _.defaults({
                    ready: function() {
                        self._retrieveDraft(options, context);
                    }
                }, options),
                context);
        } else {
            sup.ready.call(this, options, context);
        }
    },

    /*
     * Destroys the object.
     *
     * If destruction is successful, we'll reset the needDraft state so we'll
     * look up the draft the next time an operation is performed.
     */
    destroy: function(options, context) {
        options = _.bindCallbacks(options || {});

        this.ready(
            _.defaults({
                ready: function() {
                    _super(this).destroy.call(
                        this,
                        _.defaults({
                            success: function() {
                                /* We need to fetch the draft resource again. */
                                this._needDraft = true;

                                if (_.isFunction(options.success)) {
                                    options.success.apply(context, arguments);
                                }
                            }
                        }, options),
                        this);
                }
            }, options),
            this);
    },

    /*
     * Custom URL implementation which will return the special draft resource
     * if we have yet to redirect and otherwise delegate to the prototype
     * implementation.
     */
    url: function() {
        var parentObject,
            links,
            linkName;

        if (this._needDraft) {
            parentObject = this.get('parentObject');
            linkName = _.result(this, 'listKey');
            links = parentObject.get('links');

            /*
             * Chrome hyper-aggressively caches things it shouldn't, and
             * appears to do so in a subtly broken way.
             *
             * If we do a DELETE on a reply's URL, then later a GET (resulting
             * from a redirect from a GET to draft/), Chrome will somehow get
             * confused and associate the GET's caching information with a 404.
             *
             * In order to prevent this, we need to make requests to draft/
             * appear unique. We can do this by appending the timestamp here.
             * Chrome will no longer end up with broken state for our later
             * GETs.
             *
             * Much of this is only required in the case of sqlite, which,
             * with Django, may reuse row IDs, causing problems when making
             * a reply, deleting, and making a new one. In production, this
             * shouldn't be a problem, but it's very confusing during
             * development.
             */
            return links[linkName].href + 'draft/?' + $.now();
        } else {
            return _super(this).url.call(this);
        }
    },

    /*
     * Try to retrieve an existing draft from the server. This uses the
     * special draft/ resource within the resource list, which will redirect to
     * an existing draft if one exists.
     */
    _retrieveDraft: function(options, context) {
        var self = this;

        if (!RB.UserSession.instance.get('authenticated')) {
            if (options.error) {
                options.error.call(context, {
                    errorText: gettext('You must be logged in to retrieve the draft.')
                });
            }

            return;
        }

        Backbone.Model.prototype.fetch.call(this, {
            success: function() {
                /*
                 * There was an existing draft, and we were redirected to it
                 * and pulled data from it. We're done.
                 */
                self._needDraft = false;

                if (options && _.isFunction(options.ready)) {
                    options.ready.call(context);
                }
            },
            error: function(model, xhr) {
                if (xhr.status === 404) {
                    /*
                     * We now know we don't have an existing draft to work with,
                     * and will eventually need to POST to create a new one.
                     */
                    self._needDraft = false;
                    options.ready.call(context);
                } else if (options && _.isFunction(options.error)) {
                    options.error.call(context, xhr, xhr.status);
                }
            }
        });
    }
};
