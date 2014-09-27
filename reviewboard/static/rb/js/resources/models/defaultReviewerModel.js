/*
 * A registered default reviewer.
 *
 * Default reviewers auto-populate the list of reviewers for a review request
 * based on the files modified.
 *
 * The support for default reviewers is currently limited to the most basic
 * information. The lists of users, repositories and groups cannot yet be
 * provided.
 */
RB.DefaultReviewer = RB.BaseResource.extend({
    defaults: _.defaults({
        name: null,
        fileRegex: null
    }, RB.BaseResource.prototype.defaults),

    rspNamespace: 'default_reviewer',

    /*
     * Returns the URL to the resource.
     */
    url: function() {
        var url = SITE_ROOT + (this.get('localSitePrefix') || '') +
                  'api/default-reviewers/';

        if (!this.isNew()) {
            url += this.id + '/';
        }

        return url;
    },

    /*
     * Generates a payload for sending to the server.
     */
    toJSON: function() {
        return {
            name: this.get('name'),
            file_regex: this.get('fileRegex')
        };
    },

    /*
     * Parses the payload from the server.
     */
    parseResourceData: function(rsp) {
        return {
            name: rsp.name,
            fileRegex: rsp.file_regex
        };
    }
});
