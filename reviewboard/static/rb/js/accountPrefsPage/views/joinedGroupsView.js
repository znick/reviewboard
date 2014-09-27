(function() {


var GroupMembershipItem,
    GroupMembershipItemView,
    SiteGroupsView;


/*
 * An item representing the user's membership with a group.
 *
 * This keeps track of the group's information and the membership state
 * for the user. It also allows changing that membership.
 *
 * This provides two actions: 'Join', and 'Leave'.
 */
GroupMembershipItem = Djblets.Config.ListItem.extend({
    defaults: _.defaults({
        localSiteName: null,
        displayName: null,
        groupName: null,
        joined: false,
        showRemove: false,
        url: null
    }, Djblets.Config.ListItem.prototype.defaults),

    /*
     * Initializes the item.
     *
     * The item's name and URL will be taken from the serialized group
     * information, and a proxy ReviewGroup will be created to handle
     * membership.
     */
    initialize: function() {
        var name = this.get('name'),
            localSiteName = this.get('localSiteName');

        Djblets.Config.ListItem.prototype.initialize.call(this);

        this.set({
            text: name,
            editURL: this.get('url')
        });

        this.group = new RB.ReviewGroup({
            id: this.get('reviewGroupID'),
            name: name,
            localSitePrefix: (localSiteName ? 's/' + localSiteName + '/' : '')
        });

        this.on('change:joined', this._updateActions, this);
        this._updateActions();
    },

    /*
     * Joins the group.
     *
     * This will add the user to the group, and set the 'joined' property
     * to true upon completion.
     */
    joinGroup: function() {
        this.group.addUser(
            RB.UserSession.instance.get('username'),
            {
                success: function() {
                    this.set('joined', true);
                }
            },
            this);
    },

    /*
     * Leaves the group.
     *
     * This will remove the user from the group, and set the 'joined' property
     * to false upon completion.
     */
    leaveGroup: function() {
        this.group.removeUser(
            RB.UserSession.instance.get('username'),
            {
                success: function() {
                    this.set('joined', false);
                }
            },
            this);
    },

    /*
     * Updates the list of actions.
     *
     * This will replace the existing action, if any, with a new action
     * allowing the user to join or leave the group, depending on their
     * current membership status.
     */
    _updateActions: function() {
        if (this.get('joined')) {
            this.actions = [{
                id: 'leave',
                label: gettext('Leave')
            }];
        } else {
            this.actions = [{
                id: 'join',
                label: gettext('Join')
            }];
        }

        this.trigger('actionsChanged');
    }
});


/*
 * Provides UI for showing a group membership.
 *
 * This will display the group information and provide buttons for
 * the Join/Leave actions.
 */
GroupMembershipItemView = Djblets.Config.ListItemView.extend({
    actionHandlers: {
        'join': '_onJoinClicked',
        'leave': '_onLeaveClicked'
    },

    template: _.template([
        '<span class="config-group-name">',
        ' <a href="<%- editURL %>"><%- text %></a>',
        '</span>',
        '<span class="config-group-display-name"><%- displayName %></span>'
    ].join('')),

    /*
     * Handler for when Join is clicked.
     *
     * Tells the model to join the group.
     */
    _onJoinClicked: function() {
        this.model.joinGroup();
    },

    /*
     * Handler for when Leave is clicked.
     *
     * Tells the model to leave the group.
     */
    _onLeaveClicked: function() {
        this.model.leaveGroup();
    }
});


/*
 * Displays a list of group membership items, globally or for a Local Site.
 *
 * If displaying for a Local Site, then the name of the site will be shown
 * before the list.
 *
 * Each group in the list will be shown as an item with Join/Leave buttons.
 *
 * The list of groups are filterable. When filtering, if there are no groups
 * that match the filter, then the whole view will be hidden.
 */
SiteGroupsView = Backbone.View.extend({
    template: _.template([
        '<% if (name) { %>',
        ' <h3><%- name %></h3>',
        '<% } %>',
        '<div class="groups" />'
    ].join('')),

    /*
     * Initializes the view.
     *
     * This will create a list for all groups in this view.
     */
    initialize: function(options) {
        this.name = options.name;
        this.collection = new RB.FilteredCollection(null, {
            collection: new Backbone.Collection(options.groups, {
                model: GroupMembershipItem
            })
        });
        this.groupList = new Djblets.Config.List({}, {
            collection: this.collection
        });
    },

    /*
     * Renders the view.
     */
    render: function() {
        this._listView = new Djblets.Config.ListView({
            ItemView: GroupMembershipItemView,
            model: this.groupList
        });

        this.$el.html(this.template({
            name: this.name
        }));

        this._listView.render();
        this._listView.$el
            .addClass('box-recessed')
            .appendTo(this.$('.groups'));

        return this;
    },

    /*
     * Filters the list of groups by name.
     *
     * If no groups are found, then the view will hide itself.
     */
    filterBy: function(name) {
        this.collection.setFilters({
            'name': name
        });

        this.$el.setVisible(this.collection.length > 0);
    }
});


/*
 * Provides UI for managing a user's group memberships.
 *
 * All accessible groups will be shown to the user, sectioned by
 * Local Site. This list is filterable through a search box at the top of
 * the view.
 *
 * Each group entry provides a button for joining or leaving the group,
 * allowing users to manage their memberships.
 */
RB.JoinedGroupsView = Backbone.View.extend({
    template: _.template([
        '<div class="search">',
        ' <span class="rb-icon rb-icon-search-dark"></span>',
        ' <input type="text" />',
        '</div>',
        '<div class="group-lists" />'
    ].join('')),

    events: {
        'keyup .search input': '_onGroupSearchChanged',
        'change .search input': '_onGroupSearchChanged'
    },

    /*
     * Initializes the view.
     */
    initialize: function(options) {
        this.groups = options.groups;

        this._$listsContainer = null;
        this._$search = null;
        this._searchText = null;
        this._groupViews = [];
    },

    /*
     * Renders the view.
     *
     * This will set up the elements and the list of SiteGroupsViews.
     */
    render: function() {
        this.$el.html(this.template());

        this._$listsContainer = this.$('.group-lists');
        this._$search = this.$('.search input');

        _.each(this.groups, function(groups, localSiteName) {
            var view;

            if (groups.length > 0) {
                view = new SiteGroupsView({
                    name: localSiteName,
                    groups: groups
                });

                view.$el.appendTo(this._$listsContainer);
                view.render();

                this._groupViews.push(view);
            }
        }, this);

        return this;
    },

    /*
     * Handler for when the search box changes.
     *
     * This will instruct the SiteGroupsViews to filter their contents
     * by the text entered into the search box.
     */
    _onGroupSearchChanged: function() {
        var text = this._$search.val();

        if (text !== this._searchText) {
            this._searchText = text;

            _.each(this._groupViews, function(groupView) {
                groupView.filterBy(this._searchText);
            }, this);
        }
    }
});


})();
