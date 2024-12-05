<template>
  <div
    ref="dropdown"
    class="group relative flex h-8"
  >
    <div class="absolute bg-zinc-800 bg-opacity-80 px-2 py-1 text-white left-1/2 -translate-x-1/2 z-100 bottom-full whitespace-nowrap rounded-md mb-[2px] text-sm htk-hidden group-hover:block">
      Select view
    </div>
    <i class="ri-article-line absolute top-1/2 -translate-y-1/2 left-0 pl-2" />

    <div
      class="bg-white border border-zinc-300 rounded-md px-8 px-1 flex items-center text-sm text-zinc-700 focus:outline-none appearance-none min-w-52 cursor-pointer"
      @click="isOpen = !isOpen"
    >
      <span>{{ selectedView || 'Choose a view' }}</span>
      <i class="ri-arrow-down-s-line text-zinc-400 absolute inset-y-0 right-0 flex items-center pr-2" />
    </div>
    <div
      v-if="isOpen"
      class="absolute z-10 mt-8 w-full bg-white border border-zinc-300 rounded-md shadow-lg overflow-hidden"
    >
      <ul>
        <li
          v-for="name in Object.keys(views).sort((a, b) => (views[a].edit ? 1 : 0) - (views[b].edit ? 1 : 0))"
          :key="name"
          class="px-2 py-1 hover:bg-neutral-100 cursor-pointer flex items-center"
          @click="selectView(name)"
        >
          <span class="text-sm grow">{{ name }}</span>
          <button
            v-if="loggedIn && views[name].edit"
            class="htk-btn htk-btn-ghost htk-btn-sm htk-btn-icon"
            @click="editView(name); $event.stopPropagation()"
          >
            <i class="ri-pencil-line" />
          </button>
          <button
            v-if="loggedIn && views[name].edit"
            class="htk-btn htk-btn-ghost htk-btn-sm htk-btn-icon"
            @click="deleteView(name); $event.stopPropagation()"
          >
            <i class="ri-delete-bin-line" />
          </button>
          <button
            v-if="loggedIn"
            class="htk-btn htk-btn-ghost htk-btn-sm htk-btn-icon"
            @click="copyView(name); $event.stopPropagation()"
          >
            <i class="ri-file-copy-line" />
          </button>
        </li>
        <li
          v-if="loggedIn"
          class="border-t border-zinc-300"
        />
        <li
          v-if="loggedIn"
          class="px-2 py-1 hover:bg-neutral-100 cursor-pointer flex items-center"
          @click="newView()"
        >
          <span class="text-sm grow">New View</span>
        </li>
      </ul>
    </div>
  </div>
</template>

<script>
module.exports = {
    props: {
        value: String,
        views: Object,
        loggedIn: Boolean
    },
    data() {
        return {
            selectedView: this.value,
            isOpen: false
        };
    },
    watch: {
        value(newValue) {
            this.selectedView = newValue;
        }
    },
    methods: {
        selectView(name) {
            this.selectedView = name;
            this.isOpen = false;
            this.$emit('change', name);
        },
        copyView(name) {
            this.isOpen = false;
            this.$emit('copy', name);
        },
        editView(name) {
            this.isOpen = false;
            this.$emit('edit', name);
        },
        deleteView(name) {
            this.isOpen = false;
            this.$emit('delete', name);
        },
        newView() {
            this.isOpen = false;
            this.$emit('new');
        },
        handleClickOutside(event) {
            if (!this.$refs.dropdown.contains(event.target)) {
                this.isOpen = false;
            }
        }
    },
    mounted() {
        document.addEventListener('click', this.handleClickOutside);
    },
    beforeDestroy() {
        document.removeEventListener('click', this.handleClickOutside);
    }
};
</script>
