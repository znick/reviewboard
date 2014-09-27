{% load djblets_js reviewtags %}
        el: document.body,
        reviewRequestData: {
            bugTrackerURL: "{% if review_request.repository.bug_tracker %}{% url 'bug_url' review_request.display_id '--bug_id--' %}{% endif %}",
            id: {{review_request.display_id}},
            localSitePrefix: "{% if review_request.local_site %}s/{{review_request.local_site.name}}/{% endif %}",
            branch: "{{review_request_details.branch|escapejs}}",
            bugsClosed: {{review_request_details.get_bug_list|json_dumps}},
{% if draft.changedesc %}
            changeDescription: "{{draft.changedesc.text|escapejs}}",
{% endif %}
            description: "{{review_request_details.description|escapejs}}",
            hasDraft: {{draft|yesno:'true,false'}},
            lastUpdatedTimestamp: {{review_request.last_updated|json_dumps}},
            public: {{review_request.public|yesno:'true,false'}},
{% if review_request.repository %}
            repository: new RB.Repository({
{%  with repo=review_request.repository %}
{%   with scmtool=repo.get_scmtool %}
                id: {{repo.id}},
                localSitePrefix: '{% if review_request.local_site %}s/{{review_request.local_site.name}}/{% endif %}',
                name: '{{repo.name|escapejs}}',
                requiresBasedir: {{scmtool.get_diffs_use_absolute_paths|yesno:'false,true'}},
                requiresChangeNumber: {{scmtool.supports_pending_changesets|yesno:'true,false'}},
                scmtoolName: '{{scmtool.name|escapejs}}',
                supportsPostCommit: {{repo.supports_post_commit|yesno:'true,false'}}
{%   endwith %}
{%  endwith %}
            }),
{% endif %}
            reviewURL: "{{review_request.get_absolute_url|escapejs}}",
            state: RB.ReviewRequest.{% if review_request.status == 'P' %}PENDING{% elif review_request.status == 'D' %}CLOSE_DISCARDED{% elif review_request.status == 'S' %}CLOSE_SUBMITTED{% endif %},
            summary: "{{review_request_details.summary|escapejs}}",
            targetGroups: [{% spaceless %}
{% for group in review_request_details.target_groups.all %}
                {
                    name: "{{group.name|escapejs}}",
                    url: "{{group.get_absolute_url}}"
                }{% if not forloop.last %},{% endif %}
{% endfor %}{% endspaceless %}],
            targetPeople: [{% spaceless %}
{% for user in review_request_details.target_people.all %}
                {
                    username: "{{user.username|escapejs}}",
                    url: "{% url 'user' user %}"
                }{% if not forloop.last %},{% endif %}
{% endfor %}{% endspaceless %}],
            testingDone: "{{review_request_details.testing_done|escapejs}}"
        },
        editorData: {
            mutableByUser: {{mutable_by_user|yesno:'true,false'}},
            statusMutableByUser: {{status_mutable_by_user|yesno:'true,false'}},
            fileAttachmentComments: {
{% if all_file_attachments %}
{%  for file_attachment in all_file_attachments %}
                {{file_attachment.id}}: {% file_attachment_comments file_attachment %}{% if not forloop.last %},{% endif %}
{%  endfor %}
{% endif %}
            }
        }
