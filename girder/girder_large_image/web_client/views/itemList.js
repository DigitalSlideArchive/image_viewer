import $ from 'jquery';
import _ from 'underscore';
import Backbone from 'backbone';
import Vue from 'vue';

import { getCurrentUser } from '@girder/core/auth';
import { wrap } from '@girder/core/utilities/PluginUtils';
import { getApiRoot } from '@girder/core/rest';
import { AccessType } from '@girder/core/constants';
import { formatSize, parseQueryString, splitRoute } from '@girder/core/misc';
import router from '@girder/core/router';
import HierarchyWidget from '@girder/core/views/widgets/HierarchyWidget';
import ItemCollection from '@girder/core/collections/ItemCollection';
import FolderListWidget from '@girder/core/views/widgets/FolderListWidget';
import ItemListWidget from '@girder/core/views/widgets/ItemListWidget';

import largeImageConfig from './configView';
import { addToRoute } from '../routes';

import '../stylesheets/itemList.styl';
import ItemListTemplate from '../templates/itemList.pug';
import { MetadatumWidget, validateMetadataValue } from './metadataWidget';

import TableConfigDialog from './TableConfigDialog.vue';
import TableViewSelect from './TableViewSelect.vue';

ItemCollection.prototype.pageLimit = Math.max(250, ItemCollection.prototype.pageLimit);

function onItemClick(item) {
    if (this.itemListView && this.itemListView.onItemClick) {
        if (this.itemListView.onItemClick(item)) {
            return;
        }
    }
    router.navigate('item/' + item.get('_id'), { trigger: true });
}

wrap(HierarchyWidget, 'initialize', function (initialize, settings) {
    settings = settings || {};
    if (settings.paginated === undefined) {
        settings.paginated = true;
    }
    if (settings.onItemClick === undefined) {
        settings.onItemClick = onItemClick;
    }
    return initialize.call(this, settings);
});

wrap(HierarchyWidget, 'render', function (render) {
    render.call(this);
    if (this.parentModel.resourceName !== 'folder') {
        this.$('.g-folder-list-container').toggleClass('hidden', false);
    }
    if (!this.$('#flattenitemlist').length && this.$('.g-item-list-container').length && this.itemListView && this.itemListView.setFlatten) {
        $('.g-checked-actions').after(`
            <div class="group relative inline-block flex items-center">
                <div class="absolute bg-zinc-800 bg-opacity-80 px-2 py-1 text-white left-1/2 -translate-x-1/2 bottom-full rounded-md mb-[2px] text-sm whitespace-nowrap htk-hidden group-hover:block">
                    Show items in this folder and all subfolders
                </div>
                <input type="checkbox" id="flattenitemlist" style="margin:0 !important">
                <span class="mx-1 text-sm">Subfolders</span>
            </div>`
        );
        if ((this.itemListView || {})._recurse && this.parentModel.resourceName === 'folder') {
            this.$('#flattenitemlist').prop('checked', true);
            this.$('.g-folder-list-container').toggleClass('hidden', this.itemListView._hideFoldersOnFlatten);
        }
        this.events['click #flattenitemlist'] = (evt) => {
            this.itemListView.setFlatten(this.$('#flattenitemlist').is(':checked'));
        };
        this.delegateEvents();
    }
    if (this.$('#flattenitemlist').length && this.parentModel.get('_modelType') !== 'folder') {
        this.$('.li-flatten-item-list').addClass('htk-hidden');
    } else {
        this.$('.li-flatten-item-list').removeClass('htk-hidden');
    }

    const updateChecked = () => {
        // const resources = this._getCheckedResourceParam();
        // TODO: handle checked resources for apps
    };

    this.listenTo(this.itemListView, 'g:checkboxesChanged', updateChecked);
    this.listenTo(this.folderListView, 'g:checkboxesChanged', updateChecked);
});

wrap(FolderListWidget, 'checkAll', function (checkAll, checked) {
    if (checked && (this.parentView.itemListView || {})._recurse) {
        return;
    }
    return checkAll.call(this, checked);
});

wrap(ItemListWidget, 'initialize', function (initialize, settings) {
    this._inInit = true;
    const result = initialize.call(this, settings);
    delete this._hasAnyLargeImage;

    this._confList = () => {
        let list;
        if (!this._liconfig) {
            return undefined;
        }
        // If the named list is not valid, revert to the default list
        if (!this._namedList || !this._liconfig.namedItemLists || !this._liconfig.namedItemLists[this._namedList]) {
            this._namedList = this._liconfig.defaultItemList;
        }
        if (this.$el.closest('.modal-dialog').length) {
            list = this._liconfig.itemListDialog;
        } else if (this._namedList && this._liconfig.namedItemLists && this._liconfig.namedItemLists[this._namedList]) {
            list = this._liconfig.namedItemLists[this._namedList];
        } else {
            list = this._liconfig.itemList;
        }
        if (list.group) {
            let group = list.group;
            group = !group.keys ? { keys: group } : group;
            group.keys = Array.isArray(group.keys) ? group.keys : [group.keys];
            group.keys = group.keys.filter((g) => !g.includes(',') && !g.includes(':'));
            if (!group.keys.length) {
                group = undefined;
            }
            list.group = group;
        }
        return list;
    };

    largeImageConfig.getConfigFile(settings.folderId, true, (val) => {
        if (!settings.folderId) {
            this._liconfig = val;
        }
        if (_.isEqual(val, this._liconfig) && !this._recurse) {
            this._inInit = false;
            this.render();
            return;
        }
        if (!_.isEqual(val, this._liconfig) && !this.$el.closest('.modal-dialog').length && val) {
            this._liconfig = val;
            const list = this._confList();
            if (list.layout && list.layout.flatten !== undefined) {
                this._recurse = !!list.layout.flatten;
                this.parentView.$('#flattenitemlist').prop('checked', this._recurse);
            }
            this._hideFoldersOnFlatten = !!(list.layout && list.layout.flatten === 'only');
            this.parentView.$('.g-folder-list-container').toggleClass('hidden', this._hideFoldersOnFlatten);
        }
        delete this._lastSort;
        this._liconfig = val;
        const curRoute = Backbone.history.fragment;
        const routeParts = splitRoute(curRoute);
        const query = parseQueryString(routeParts.name);
        this._namedList = query.namedList || undefined;
        let update = false;
        if (query.sort) {
            this._lastSort = query.sort.split(',').map((chunk) => {
                const parts = chunk.split(':');
                return {
                    type: parts[0],
                    value: parts[1],
                    dir: parts[2]
                };
            });
            update = true;
        } else if (this._confList && this._confList() && this._confList().defaultSort && this._confList().defaultSort.length) {
            this._lastSort = this._confList().defaultSort;
            update = true;
        }
        if (query.filter || this._recurse) {
            this._generalFilter = query.filter;
            this._setFilter(false);
            update = true;
        }
        this._inInit = false;
        if (update) {
            this._setSort();
        } else {
            this.render();
        }
    });
    this.events['click .sortable'] = (evt) => sortColumn.call(this, evt);
    this.events['click .li-item-list-cell-filter'] = (evt) => itemListCellFilter.call(this, evt);
    this.events['click .large_image_metadata.lientry_edit'] = (evt) => itemListMetadataEdit.call(this, evt);
    this.events['change .large_image_metadata.lientry_edit'] = (evt) => itemListMetadataEdit.call(this, evt);
    this.events['input .large_image_metadata.lientry_edit'] = (evt) => itemListMetadataEdit.call(this, evt);
    this.delegateEvents();
    this.setFlatten = (flatten) => {
        if (!!flatten !== !!this._recurse) {
            this._recurse = !!flatten;
            this.parentView.$('.g-folder-list-container').toggleClass('hidden', this._hideFoldersOnFlatten && this._recurse);
            this._setFilter();
            this.render();
        }
    };
    return result;
});

wrap(ItemListWidget, 'render', function (render) {
    this.$el.closest('.modal-dialog').addClass('li-item-list-dialog');
    if (!this.$el.children().length) {
        this.$el.html('<span class="icon-spin1 animate-spin" title="Loading item list"/>');
    }

    /* Chrome limits the number of connections to a single domain, which means
     * that time-consuming requests for thumbnails can bind-up the web browser.
     * To avoid this, limit the maximum number of thumbnails that are requested
     * at a time.  At this time (2016-09-27), Chrome's limit is 6 connections;
     * to preserve some overhead, use a number a few lower than that. */
    var maxSimultaneous = 3;

    /**
     * When we might need to load another image, check how many are waiting or
     * currently being loaded, and ask an appropriate additional number to
     * load.
     *
     * @param {jquery element} parent parent under which the large_image
     *      thumbnails are located.
     */
    function _loadMoreImages(parent) {
        var loading = $('.large_image_thumbnail img.loading,.large_image_associated img.loading', parent).length;
        if (maxSimultaneous > loading) {
            $('.large_image_thumbnail img.waiting,.large_image_associated img.waiting', parent).slice(0, maxSimultaneous - loading).each(function () {
                var img = $(this);
                img.removeClass('waiting').addClass('loading');
                img.attr('src', img.attr('deferred-src'));
            });
        }
    }

    this._saveTableConfig = ({ config, name, newView, originalName }) => {
        // Update or add the named view
        if (!this._liconfig) {
            this._liconfig = {};
        }
        if (!this._liconfig.namedItemLists) {
            this._liconfig.namedItemLists = {};
        }
        if (newView) {
            // Need to make the view name unique
            let foundView = this._liconfig.namedItemLists[name];
            while (foundView) {
                name += ' Copy';
                foundView = this._liconfig.namedItemLists[name];
            }
            const configCopy = JSON.parse(JSON.stringify(config));
            configCopy.edit = true;
            this._liconfig.namedItemLists[name] = configCopy;
        } else {
            const foundView = this._liconfig.namedItemLists[originalName];
            if (foundView) {
                if (originalName !== name) {
                    // Need to make the view name unique
                    let duplicate = this._liconfig.namedItemLists[name];
                    while (duplicate) {
                        name += ' Copy';
                        duplicate = this._liconfig.namedItemLists[name];
                    }
                    delete this._liconfig.namedItemLists[originalName];
                    this._liconfig.namedItemLists[name] = foundView;
                }
                foundView.columns = config.columns;
                foundView.layout = config.layout;
                foundView.edit = true;
            } else {
                // This may occur if we are moving an old existing default view to a named view
                const configCopy = JSON.parse(JSON.stringify(config));
                configCopy.edit = true;
                this._liconfig.namedItemLists[name] = configCopy;
            }
        }
        this._updateNamedList(name, true);
        // Save the new configuration to the yaml file
        largeImageConfig.saveConfigFile(this.parentView.parentModel.id, this._liconfig, null);
        itemListRender.apply(this);
    };

    this._deleteTableConfig = (name) => {
        if (!this._liconfig) {
            return;
        }
        delete this._liconfig.namedItemLists[name];
        // If we are deleting the current view, clear the namedList from the URL
        if ((this._namedList || '') === name) {
            addToRoute({ namedList: undefined });
            this._namedList = undefined;
        }
        itemListRender.apply(this);
        largeImageConfig.saveConfigFile(this.parentView.parentModel.id, this._liconfig, null);
    };

    this._allColumns = () => {
        if (this._liconfig && this._liconfig.allColumns) {
            return this._liconfig.allColumns;
        }
        const allColumns = [
            { type: 'image', value: 'thumbnail', title: 'Thumbnail' },
            { type: 'image', value: 'label', title: 'Label' },
            { type: 'record', value: 'controls', title: 'Controls' },
            { type: 'record', value: 'name', title: 'Name' },
            { type: 'record', value: 'size', title: 'Size' }
        ];
        const allColumnsMap = {};
        this.collection.toArray().forEach((item) => {
            const value = item.get('meta') || {};
            for (const key in value) {
                if (!allColumnsMap[key]) {
                    allColumnsMap[key] = true;
                    allColumns.push({
                        type: 'metadata',
                        value: key,
                        title: key.replace(/[^a-zA-Z0-9]+/g, ' ')
                            .split(' ')
                            .filter((word) => word.length > 0)
                            .map((word) =>
                                word.charAt(0).toUpperCase() + word.slice(1).toLowerCase()
                            )
                            .join(' ')
                    });
                }
            }
        });
        return allColumns;
    };

    /**
     * Set sort on the collection and perform a debounced re-fetch.
     */
    this._setSort = () => {
        if (!this._inFetch) {
            this._inFetch = true;
            this._needsFetch = false;
            if (this._lastSort) {
                this.collection.comparator = _.constant(0);
                this.collection.sortField = JSON.stringify(this._lastSort.map((e) => [
                    (e.type === 'metadata' ? 'meta.' : '') + e.value,
                    e.dir === 'down' ? 1 : -1
                ]));
            }
            this.collection._totalCount = 0;
            this.collection.fetch(_.extend({}, { folderId: this.parentView.parentModel.id }, this.collection.params), true).done(() => {
                const oldPages = this._totalPages;
                const pages = Math.ceil(this.collection.getTotalCount() / this.collection.pageLimit);
                this._totalPages = pages;
                // recheck if this has large images
                this._hasAnyLargeImage = !!_.some(this.collection.toArray(), function (item) {
                    return item.has('largeImage');
                });
                this._inFetch = false;
                if (oldPages !== pages || this.collection.offset !== this.collection.size()) {
                    this.collection.offset = this.collection.size();
                    this.trigger('g:paginated');
                    this.collection.trigger('g:changed');
                } else {
                    itemListRender.apply(this, _.rest(arguments));
                }
                if (this._needsFetch) {
                    this._setSort();
                }
            });
        } else {
            this._needsFetch = true;
        }
    };

    /**
     * Return true if we handle the click
     */
    this.onItemClick = (item) => {
        const list = this._confList();
        const nav = (list || {}).navigate;
        if (!nav || (!nav.type && !nav.name) || nav.type === 'item') {
            return false;
        }
        if (nav.type === 'itemList') {
            if ((nav.name || '') === (this._namedList || '')) {
                return false;
            }
            if (!this._liconfig || !this._liconfig.namedItemLists || (nav.name && !this._liconfig.namedItemLists[nav.name])) {
                return false;
            }
            this._updateNamedList(nav.name, false);
            if (list.group) {
                this._generalFilter = '';
                list.group.keys.forEach((key) => {
                    const cell = this.$el.find(`[g-item-cid="${item.cid}"] [column-value="${key}"]`);
                    if (cell.length) {
                        addCellToFilter.call(this, cell, false);
                    }
                });
            }
            this._setFilter(false);
            this._setSort();
            addToRoute({ namedList: this._namedList, filter: this._generalFilter });
            return true;
        }
        if (nav.type === 'open') {
            if (item._href) {
                window.open(item._href, '_blank');
                return true;
            }
        }
        return false;
    };

    this._updateNamedList = (name, update) => {
        name = name || '';
        if ((this._namedList || '') !== name) {
            this._namedList = name;
            if (update !== false) {
                addToRoute({ namedList: this._namedList });
                this._setSort();
            }
        }
    };

    this._updateFilter = (evt) => {
        this._generalFilter = $(evt.target).val().trim();
        this._setFilter();
        addToRoute({ filter: this._generalFilter });
    };

    this._clearFilter = (evt) => {
        this._generalFilter = '';
        this._setFilter();
        addToRoute({ filter: this._generalFilter });
    };

    this._unescapePhrase = (val) => {
        if (val !== undefined) {
            val = val.replace('\\\'', '\'').replace('\\"', '"').replace('\\\\', '\\');
        }
        return val;
    };

    this._setFilter = (update) => {
        const val = this._generalFilter;
        let filter;
        const usedPhrases = {};
        const columns = (this._confList() || {}).columns || [];
        if (val !== undefined && val !== '' && columns.length) {
            // a value can be surrounded by single or double quotes, which will
            // be removed.
            const quotedValue = /((?:"((?:[^\\"]|\\\\|\\")*)(?:"|$)|'((?:[^\\']|\\\\|\\')*)(?:'|$)|([^:,\s]+)))/g;
            const phraseRE = new RegExp(
                new RegExp('((?:' + quotedValue.source + ':|))').source +
                /(-?)/.source +
                quotedValue.source +
                new RegExp('((?:,' + quotedValue.source + ')*)').source, 'g');
            filter = [];
            [...val.matchAll(phraseRE)].forEach((match) => {
                const coltag = this._unescapePhrase(match[5] || match[4] || match[3]);
                const phrase = this._unescapePhrase(match[10] || match[9] || match[8]);
                const negation = match[6] === '-';
                var phrases = [{ phrase: phrase, exact: match[8] !== undefined }];
                if (match[11]) {
                    [...match[11].matchAll(quotedValue)].forEach((submatch) => {
                        const subphrase = this._unescapePhrase(submatch[4] || submatch[3] || submatch[2]);
                        // remove dupes?
                        if (subphrase && subphrase.length) {
                            phrases.push({ phrase: subphrase, exact: submatch[2] !== undefined });
                        }
                    });
                }
                const key = `${coltag || ''}:` + phrases.map((p) => p.phrase + (p.exact ? '__exact__' : '')).join('|||');
                if (!phrases.length || usedPhrases[key]) {
                    return;
                }
                usedPhrases[key] = true;
                const clause = [];
                phrases.forEach(({ phrase, exact }) => {
                    const numval = +phrase;
                    /* If numval is a non-zero number not in exponential
                     * notation, delta is the value of one for the least
                     * significant digit.  This will be NaN if phrase is not a
                     * number. */
                    const delta = Math.abs(+numval.toString().replace(/\d(?=.*[1-9](0*\.|)0*$)/g, '0').replace(/[1-9]/, '1'));
                    // escape for regex
                    phrase = phrase.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

                    columns.forEach((col) => {
                        let key;
                        if (coltag &&
                            coltag.localeCompare(col.title || col.value, undefined, { sensitivity: 'accent' }) &&
                            coltag.localeCompare(col.value, undefined, { sensitivity: 'accent' })
                        ) {
                            return;
                        }
                        if (col.type === 'record' && col.value !== 'controls') {
                            key = col.value;
                        } else if (col.type === 'metadata') {
                            key = 'meta.' + col.value;
                        }
                        if (!coltag && !exact) {
                            const r = new RegExp('^' + (phrase.substr(phrase.length - 1) === ':' ? phrase.substr(0, phrase.length - 1) : phrase), 'i');
                            if (r.exec(col.value) || r.exec(col.title || col.value)) {
                                clause.push({ [key]: { $exists: true } });
                            }
                        }
                        if (key && exact) {
                            clause.push({ [key]: { $regex: '^' + phrase + '$', $options: 'i' } });
                            if (!_.isNaN(numval)) {
                                clause.push({ [key]: numval });
                            }
                        } else if (key) {
                            clause.push({ [key]: { $regex: phrase, $options: 'i' } });
                            if (!_.isNaN(numval)) {
                                clause.push({ [key]: numval });
                                if (numval > 0 && delta) {
                                    clause.push({ [key]: { $gte: numval, $lt: numval + delta } });
                                } else if (numval < 0 && delta) {
                                    clause.push({ [key]: { $lte: numval, $gt: numval + delta } });
                                }
                            }
                        }
                    });
                });
                if (clause.length > 0) {
                    filter.push(!negation ? { $or: clause } : { $nor: clause });
                } else if (!negation) {
                    filter.push({ $or: [{ _no_such_value_: '_no_such_value_' }] });
                }
            });
            if (filter.length === 0) {
                filter = undefined;
            } else {
                if (filter.length === 1) {
                    filter = filter[0];
                } else {
                    filter = { $and: filter };
                }
                filter = '_filter_:' + JSON.stringify(filter);
            }
        }
        const group = (this._confList() || {}).group || undefined;
        if (group) {
            if (group.keys.length) {
                let grouping = '_group_:meta.' + group.keys.join(',meta.');
                if (group.counts) {
                    for (let [gkey, gval] of Object.entries(group.counts)) {
                        if (!gkey.includes(',') && !gkey.includes(':') && !gval.includes(',') && !gval.includes(':')) {
                            if (gkey !== '_id') {
                                gkey = `meta.${gkey}`;
                            }
                            grouping += `,_count_,${gkey},meta.${gval}`;
                        }
                    }
                }
                filter = grouping + ':' + (filter || '');
            }
        }
        if (this._recurse) {
            filter = '_recurse_:' + (filter || '');
        }
        if (filter !== this._filter || filter !== (this.collection.params || {}).text) {
            this._filter = filter;
            this.collection.params = this.collection.params || {};
            this.collection.params.text = this._filter;
            if (update !== false) {
                this._setSort();
            }
        }
    };

    this.checkApps = (resources) => {
        const items = this.collection.models;
        const folders = [this.parentView.parentModel];
        const canHandle = { items: {}, folders: {} };
        // TODO: handle checked resources
        Object.entries(ItemListWidget.registeredApplications).forEach(([appname, app]) => {
            items.forEach((item) => {
                const check = app.check('item', item, this.parentView.parentModel);
                if (check) {
                    canHandle.items[item.id] = canHandle.items[item.id] || {};
                    canHandle.items[item.id][appname] = check;
                }
            });
            folders.forEach((folder) => {
                const check = app.check('item', folder, this.parentView.parentModel);
                if (check) {
                    canHandle.folders[folder.id] = canHandle.folders[folder.id] || {};
                    canHandle.folders[folder.id][appname] = check;
                }
            });
        });
        return canHandle;
    };

    /**
     * For each item in the collection, if we are navigating to something other
     * than the item, set an href property.
     */
    function adjustItemHref(availableApps) {
        this.collection.forEach((item) => {
            item._href = undefined;
            item._hrefTarget = undefined;
        });
        const list = this._confList();
        const nav = (list || {}).navigate;
        if (!nav || (!nav.type && !nav.name) || nav.type === 'item') {
            return;
        }
        if (nav.type === 'itemList') {
            if ((nav.name || '') === (this._namedList || '')) {
                return;
            }
            if (!this._liconfig || !this._liconfig.namedItemLists || (nav.name && !this._liconfig.namedItemLists[nav.name])) {
                return;
            }
            this.collection.forEach((item) => {
                item._href = `#folder/${this.parentView.parentModel.id}?namedList=` + (nav.name ? encodeURIComponent(nav.name) : '');
                let filter = '';
                if (list.group) {
                    list.group.keys.forEach((col) => {
                        let val = item.get('meta') || {};
                        col.split('.').forEach((part) => {
                            val = (val || {})[part];
                        });
                        if (/[ '\\]/.exec(col)) {
                            col = "'" + col.replace('\\', '\\\\').replace("'", "\\'") + "'";
                        }
                        if (val) {
                            val = val.replace('\\', '\\\\').replace('"', '\\"');
                            filter += ` ${col}:"${val}"`;
                        }
                    });
                }
                filter = filter.trim();
                if (filter !== '') {
                    item._href += '&filter=' + encodeURIComponent(filter);
                }
            });
        } else if (nav.type === 'open') {
            this.collection.forEach((item) => {
                let apps = availableApps.items[item.id];
                let app;
                if (nav.name && apps[nav.name]) {
                    app = apps[nav.name];
                }
                if (!app) {
                    apps = Object.entries(apps).sort(([name1, app1], [name2, app2]) => { const diff = (app1.priority || 0) - (app2.priority || 0); return diff || (ItemListWidget.registeredApplications[name1].name.toLowerCase() > ItemListWidget.registeredApplications[name2].name.toLowerCase() ? 1 : -1); });
                    app = apps[0][1];
                }
                if (app.url && app.url !== true) {
                    item._href = app.url;
                    item._hrefTarget = '_blank';
                }
            });
        }
    }

    function itemListRender() {
        if (this._inInit || this._inFetch) {
            return;
        }
        const root = this.$el.closest('.g-hierarchy-widget');
        if (!root.find('.li-item-list-filter').length) {
            let base = root.find('.g-checked-actions').eq(0);
            let func = 'after';
            if (!base.length) {
                base = root.find('.g-hierarchy-breadcrumb-bar>.breadcrumb>div').eq(0);
            }
            if (base.length) {
                base[func](`
                    <div class="g-table-view-select"></div>

                    <div class="li-item-list-filter group relative flex h-8 grow">
                        <div class="absolute bg-zinc-800 bg-opacity-80 px-2 py-1 text-white left-1/2 -translate-x-1/2 z-100 w-72 top-full rounded-md mb-[2px] text-sm htk-hidden group-hover:block">
                            <p>Matches items where all specified terms match.</p>
                            <p>Surround with single quotes to include spaces, double quotes for exact value match.</p>
                            <p>Prefix with - to exclude that value.</p>
                            <p>By default, all columns are searched. Use <column>:<value1>[,<value2>...] to require that a column matches a specified value or any of a list of specified values. Column and value names can be quoted to include spaces (single quotes for substring match, double quotes for exact value match).</p>
                            <p>If <column>:-<value1>[,<value2>...] is specified, matches will exclude the list of values.</p>
                            <p>Non-exact matches without a column specifier will also match columns that start with the specified value.</p>
                        </div>
                        <i class="ri-search-line absolute top-1/2 -translate-y-1/2 left-0 pl-3"></i>
                        <input
                          type="text"
                          class="li-item-list-filter-input bg-white border border-zinc-300 rounded-md px-1 pl-8 text-sm focus:outline-none min-w-52 w-full"
                          placeholder="Search items"
                        >
                        <button class="li-item-list-filter-clear absolute right-3 top-1/2 transform -translate-y-1/2 text-gray-500 hover:text-gray-700 focus:outline-none">
                            <i class="ri-close-line"></i>
                        </button>
                    </div>
                `);
                this._tableViewSelectVue = null; // We'll need to recreate this

                if (this._generalFilter) {
                    root.find('.li-item-list-filter-input').val(this._generalFilter);
                }
                this.parentView.events['change .li-item-list-filter-input'] = this._updateFilter;
                this.parentView.events['input .li-item-list-filter-input'] = this._updateFilter;
                this.parentView.events['click .li-item-list-filter-clear'] = (evt) => {
                    this.parentView.$el.find('.li-item-list-filter-input').val('');
                    this._clearFilter();
                };
                this.parentView.delegateEvents();
            }
        }

        if (!this._lastSort && this._confList() && this._confList().defaultSort && this._confList().defaultSort.length) {
            this._lastSort = this._confList().defaultSort;
            this._setSort();
            return;
        }
        const itemList = this._confList();
        if (!itemList.columns || itemList.columns.length === 0) {
            itemList.columns = [
                { type: 'record', value: 'name', title: 'Name' },
                { type: 'record', value: 'size', title: 'Size' },
                { type: 'record', value: 'controls', title: 'Controls' }
            ];
        }
        const availableApps = this.checkApps();
        adjustItemHref.call(this, availableApps);
        this.$el.html(ItemListTemplate({
            items: this.collection.toArray(),
            isParentPublic: this.public,
            hasMore: this.collection.hasNextPage(),
            formatSize: formatSize,
            checkboxes: this._checkboxes,
            downloadLinks: this._downloadLinks,
            viewLinks: this._viewLinks,
            showSizes: this._showSizes,
            highlightItem: this._highlightItem,
            selectedItemId: (this._selectedItem || {}).id,
            paginated: this._paginated,
            apiRoot: getApiRoot(),
            hasAnyLargeImage: this._hasAnyLargeImage,
            itemList: this._confList(),
            sort: this._lastSort,
            MetadatumWidget: MetadatumWidget,
            accessLevel: this.accessLevel,
            registeredApps: ItemListWidget.registeredApplications,
            availableApps: availableApps,
            parentView: this,
            AccessType: AccessType
        }));

        const TableConfigDialogConstructor = Vue.extend(TableConfigDialog);
        this._tableConfigVue = new TableConfigDialogConstructor({
            propsData: {
                config: (this._confList() || {}) || {},
                allColumns: this._allColumns(),
                name: this._namedList,
                newView: false
            }
        });
        this._tableConfigVue.$on('save', (config, name) => {
            this._saveTableConfig({ config, name, newView: false, originalName: this._tableConfigVue.name });
        });
        this._tableConfigVue.$mount(this.parentView.$el.find('.g-edit-table-view-dialog-container')[0]);

        const currentName = this._namedList;
        const views = (this._liconfig || {}).namedItemLists || {};
        if (this._tableViewSelectVue) {
            this._tableViewSelectVue.value = currentName;
            this._tableViewSelectVue.views = views;
            this._tableViewSelectVue.loggedIn = !!getCurrentUser();
        } else {
            const TableViewSelectConstructor = Vue.extend(TableViewSelect);
            this._tableViewSelectVue = new TableViewSelectConstructor({
                propsData: {
                    value: currentName,
                    views,
                    loggedIn: !!getCurrentUser()
                }
            });

            this._tableViewSelectVue.$on('change', (name) => {
                if (!this._liconfig) {
                    this._liconfig = {};
                }
                if (!this._liconfig.itemList) {
                    this._liconfig.itemList = {};
                }
                this._updateNamedList(name, true);
                this._setFilter(false);
                this._setSort();
            });

            this._tableViewSelectVue.$on('edit', (name) => {
                this._tableConfigVue.config = (this._liconfig.namedItemLists || {})[name];
                this._tableConfigVue.name = name;
                this._tableConfigVue.newView = false;
                this._tableConfigVue.$refs.dialog.show();
            });

            this._tableViewSelectVue.$on('delete', (name) => {
                this._deleteTableConfig(name);
            });

            this._tableViewSelectVue.$on('new', () => {
                if (this._liconfig === undefined) {
                    this._liconfig = {};
                }
                if (this._liconfig.namedItemLists === undefined) {
                    this._liconfig.namedItemLists = {};
                }
                let name = 'View';
                let num = 1;
                let foundView = this._liconfig.namedItemLists[name];
                while (foundView) {
                    num += 1;
                    name = `View ${num}`;
                    foundView = this._liconfig.namedItemLists[name];
                }
                const columns = [
                    { type: 'record', value: 'name' },
                    { type: 'record', value: 'size' },
                    { type: 'record', value: 'controls' }
                ];
                this._liconfig.namedItemLists[name] = { columns, edit: true };

                this._tableConfigVue.config = this._liconfig.namedItemLists[name];
                this._tableConfigVue.name = name;
                this._tableConfigVue.newView = true;
                this._tableConfigVue.$refs.dialog.show();
            });

            this._tableViewSelectVue.$on('copy', (name) => {
                if (this._liconfig === undefined) {
                    this._liconfig = {};
                }
                if (this._liconfig.namedItemLists === undefined) {
                    this._liconfig.namedItemLists = {};
                }
                const foundView = this._liconfig.namedItemLists[name];
                this._saveTableConfig({ config: foundView, name, newView: true });
            });

            this._tableViewSelectVue.$mount(this.parentView.$el.find('.g-table-view-select')[0]);
        }

        const parent = this.$el;
        this.$el.find('.large_image_thumbnail').each(function () {
            var elem = $(this);
            /* Handle images loading or failing. */
            $('img', elem).one('error', function () {
                $('img', elem).addClass('failed-to-load');
                $('img', elem).removeClass('loading waiting');
                elem.addClass('failed-to-load');
                _loadMoreImages(parent);
            });
            $('img', elem).one('load', function () {
                $('img', elem).addClass('loaded');
                $('img', elem).removeClass('loading waiting');
                _loadMoreImages(parent);
            });
        });
        _loadMoreImages(parent);
    }

    if (this._confList() && this._hasAnyLargeImage) {
        return itemListRender.apply(this, _.rest(arguments));
    }

    largeImageConfig.getSettings((settings) => {
        var items = this.collection.toArray();
        this._hasAnyLargeImage = !!_.some(items, function (item) {
            return item.has('largeImage');
        });
        if (this._confList()) {
            return itemListRender.apply(this, _.rest(arguments));
        }

        if (this._recurse && !((this.collection || {}).params || {}).text) {
            this._setFilter();
            this.render();
        }
        return this;
    });
    return this;
});

wrap(ItemListWidget, 'remove', function (remove) {
    const root = this.$el.closest('.g-hierarchy-widget');
    root.remove('.li-item-list-filter');
    delete this.parentView.events['change .li-item-list-filter-input'];
    delete this.parentView.events['input .li-item-list-filter-input'];
    this.parentView.delegateEvents();
    return remove.call(this);
});

function sortColumn(evt) {
    const icon = {
        up: 'ri-arrow-up-line',
        down: 'ri-arrow-down-line',
        none: 'ri-arrow-up-down-line'
    };
    const header = $(evt.currentTarget);
    const entry = {
        type: header.attr('column_type'),
        value: header.attr('column_value')
    };
    const sortIndicator = header.find('.sort-indicator');
    const curDir = sortIndicator.hasClass(icon.down) ? 'down' : sortIndicator.hasClass(icon.up) ? 'up' : 'none';
    const nextDir = curDir === 'down' ? 'up' : 'down';
    sortIndicator.toggleClass(icon.down, nextDir === 'down').toggleClass(icon.up, nextDir === 'up').toggleClass(icon.none, nextDir === 'none');
    entry.dir = nextDir;
    const oldSort = this._lastSort;
    if (!this._lastSort) {
        this._lastSort = [];
    }
    this._lastSort = this._lastSort.filter((e) => e.type !== entry.type || e.value !== entry.value);
    this._lastSort.unshift(entry);
    this._setSort();
    if (!_.isEqual(this._lastSort, oldSort)) {
        addToRoute({ sort: this._lastSort.map((e) => `${e.type}:${e.value}:${e.dir}`).join(',') });
    }
}

function addCellToFilter(cell, update) {
    let filter = this._generalFilter || '';
    let val = cell.attr('filter-value');
    let col = cell.attr('column-value');
    if (/[ '\\]/.exec(col)) {
        col = "'" + col.replace('\\', '\\\\').replace("'", "\\'") + "'";
    }
    val = val.replace('\\', '\\\\').replace('"', '\\"');
    filter += ` ${col}:"${val}"`;
    filter = filter.trim();
    this.$el.closest('.g-hierarchy-widget').find('.li-item-list-filter-input').val(filter);
    this._generalFilter = filter;
    if (update !== false) {
        this._setFilter();
    }
}

function itemListCellFilter(evt) {
    evt.preventDefault();
    const cell = $(evt.target).closest('.li-item-list-cell-filter');
    addCellToFilter.call(this, cell);
    addToRoute({ filter: this._generalFilter });
    this._setSort();
    return false;
}

function itemListMetadataEdit(evt) {
    evt.preventDefault();
    if (evt.type === 'click') {
        return false;
    }
    const ctrl = $(evt.target).closest('.lientry_edit');
    const columns = (this._confList() || {}).columns || [];
    const column = columns[+ctrl.attr('column-idx')];
    let tempValue = ctrl.find('.g-widget-metadata-value-input').val();
    tempValue = tempValue.trim();
    let valResult = validateMetadataValue(column, tempValue, this._lastValidationError || (tempValue === '' && !column.required));
    if (tempValue === '' && !column.required) {
        valResult = { value: tempValue };
    }
    if (!valResult) {
        this._lastValidationError = true;
        return false;
    }
    this._lastValidationError = false;
    const item = this.collection.get(ctrl.closest('[g-item-cid]').attr('g-item-cid'));
    let value = item.get('meta') || {};
    let meta;
    let key;
    column.value.split('.').forEach((part) => {
        meta = value;
        key = part;
        value = (value || {})[part];
    });
    if (value === valResult.value) {
        return;
    }
    meta[key] = valResult.value;
    item._sendMetadata(item.get('meta'));
    return false;
}

/**
 * This is a dictionary where the key is the unique application identified.
 * Each dictionary contains
 *  name: the display name
 *  icon: an optional url to an icon to display
 *  check: a method that takes (modelType, model, currentFolder) where
 *      modelType is either 'item', 'folder', or 'resource' and model is a
 *      bootstrap model or a resource dictionary of models.  The function
 *      returns an object with {url: <url>, priority: <integer>, open:
 *      <function>} where url is the url to open if possible, the open function
 *      is a method to call to open the model.  Priority affects the order that
 *      the open calls are listed in (lower is earlier).  Return undefined or
 *      false if the application cannot open this model.
 */
ItemListWidget.registeredApplications = {};

export default ItemListWidget;
