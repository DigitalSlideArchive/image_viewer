<template>
  <dialog ref="dialog">
    <div class="fixed inset-0 flex items-center justify-center text-sm z-50">
      <div
        class="bg-white flex flex-col h-full max-h-[calc(100vh-100px)] max-w-3xl overflow-hidden rounded-lg shadow-lg w-full"
      >

        <div class="flex items-center px-3 py-2 bg-neutral-200">
          <h4 class="flex-1">
            Edit View
          </h4>
        </div>

        <div class="flex flex-row flex-grow overflow-hidden">
          <div class="relative flex-1 flex flex-col p-3 bg-white shadow-md transition-all duration-300">
            <div class="flex items-center mb-2">
              <input
                v-model="editableName"
                type="text"
                class="border border-neutral-200 rounded-md w-full px-3 py-2 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-secondary focus:ring-offset-1"
                style="color: #333333"
                placeholder="Name"
              >
            </div>
            <div class="flex items-center mb-2 space-x-2">
              <label class="flex items-center space-x-2 ml-1 mr-8 font-normal">
                <input
                  type="checkbox"
                  v-model="isGrid"
                >
                <span>Display in grid</span>
              </label>
              <input
                v-model.number="gridWidth"
                type="text"
                class="border border-neutral-200 rounded-md w-16 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-secondary focus:ring-offset-1 text-right"
                style="color: #333333"
                placeholder="Width"
              >
              <span>px</span>
            </div>
            <div class="flex items-center relative">
              <input
                v-model="searchInput"
                type="text"
                class="border border-neutral-200 rounded-md w-full px-3 py-2 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-secondary focus:ring-offset-1"
                style="color: #333333"
                placeholder="Search columns"
              >
              <button
                v-if="searchInput"
                class="absolute right-3 top-1/2 transform -translate-y-1/2 text-neutral-500 hover:text-neutral-700 focus:outline-none"
                @click="searchInput = ''"
              >
                <i class="ri-close-line" />
              </button>
            </div>
            <div
              class="rounded-md flex-grow overflow-hidden transition-all duration-300 mt-3"
              style="color: #333333"
            >
              <ul class="h-full overflow-y-auto">
                <li
                  v-for="column in searchResults"
                  :key="uniqueKey(column)"
                  class="border-b border-neutral-200 h-10 px-2 py-2 flex items-center space-x-2"
                >
                  <button
                    class="htk-btn htk-btn-ghost htk-btn-sm htk-btn-icon"
                    @click="addColumn(column)"
                  >
                    <i class="ri-add-circle-line" />
                  </button>
                  <span>
                    {{ column.title }}
                  </span>
                </li>
              </ul>
            </div>
          </div>

          <div
            class="flex-1 flex flex-col flex-grow p-3 bg-neutral-100 overflow-y-auto shadow-[inset_0_-4px_6px_-2px_rgba(0,0,0,0.05)]"
          >
            <ul class="space-y-1">
              <draggable
                v-model="editableConfig.columns"
                handle=".ri-draggable"
              >
                <transition-group class="space-y-1">
                  <li
                    v-for="column in editableConfig.columns ? editableConfig.columns : []"
                    :key="column.title || column.value"
                    class="bg-white border border-neutral-200 flex flex-col items-stretch rounded-md"
                  >
                    <div class="flex items-center px-2 py-1 space-x-2 cursor-default">
                      <i class="ri-draggable cursor-grab text-lg text-neutral-500" />
                      <span class="flex-1">{{ column.title || column.value }}</span>
                      <div
                        v-if="column.type !== 'record'"
                        class="group-hover:block"
                      >
                        <button
                          class="htk-btn htk-btn-ghost htk-btn-sm htk-btn-icon"
                          @click="removeColumn(column)"
                        >
                          <i class="ri-delete-bin-line" />
                        </button>
                      </div>
                    </div>
                  </li>
                </transition-group>
              </draggable>
            </ul>
          </div>
        </div>
        <div class="bg-white border-t border-neutral-200 flex justify-end p-3 space-x-2">
          <button
            class="htk-btn htk-btn-ghost"
            @click="cancel"
          >
            Cancel
          </button>
          <button
            class="htk-btn htk-btn-primary"
            @click="save"
          >
            Save
          </button>
        </div>
      </div>
    </div>
  </dialog>
</template>

<script>
import draggable from 'vuedraggable';

module.exports = {
    components: {
        draggable
    },
    props: {
        name: String,
        config: Object,
        allColumns: Array,
        newView: Boolean
    },
    data: function () {
        return {
            editableConfig: {},
            searchInput: '',
            editableName: '',
            gridWidth: 250,
            isGrid: false,
        };
    },
    computed: {
        searchResults() {
            return this.allColumns.filter((column) => {
                if (this.editableConfig.columns.some((col) => col.type === column.type && col.value === column.value)) {
                    return false;
                }
                const lower = this.searchInput.toLowerCase();
                return column.title.toLowerCase().includes(lower) || column.value.toLowerCase().includes(lower);
            });
        }
    },
    watch: {
        name(newName) {
            this.editableName = newName;
        },
        config(newConfig) {
            this.updateConfig(newConfig);
        },
        isGrid(newIsGrid) {
            if (!this.editableConfig.layout) {
                this.editableConfig.layout = {};
            }
            this.editableConfig.layout.mode = newIsGrid ? 'grid' : 'table';
        },
        gridWidth(newWidth) {
            if (!this.editableConfig.layout) {
                this.editableConfig.layout = {};
            }
            this.editableConfig.layout['max-width'] = newWidth;
        },
    },
    created() {
        this.updateConfig(this.config);
        this.editableName = this.name;
    },
    methods: {
        updateConfig(newConfig) {
            this.editableConfig = JSON.parse(JSON.stringify(newConfig));
            if (this.editableConfig.layout) {
                this.isGrid = this.editableConfig.layout.mode === 'grid';
                this.gridWidth = this.editableConfig.layout['max-width'] || 250;
            }
        },
        save() {
            this.$emit('save', this.editableConfig, this.editableName);
            this.$refs.dialog.close();
        },
        cancel() {
            this.$refs.dialog.close();
        },
        removeColumn(column) {
            this.editableConfig.columns = this.editableConfig.columns.filter((col) => col !== column);
        },
        uniqueKey(column) {
            return column.type + '~' + column.value;
        },
        addColumn(column) {
            const key = this.uniqueKey(column);
            const col = this.allColumns.find((col) => this.uniqueKey(col) === key);
            if (col) {
                this.editableConfig.columns.push(col);
            }
        }
    }
};
</script>
