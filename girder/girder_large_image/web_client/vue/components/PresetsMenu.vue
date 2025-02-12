<script>
export default {
    props: ['itemId', 'liConfig', 'imageMetadata', 'availableModes', 'currentMode', 'currentFrame', 'currentStyle'],
    emits: ['setCurrentMode', 'setCurrentFrame', 'updateStyle'],
    data() {
        return {
            itemPresets: [],
            folderPresets: [],
            selectedPreset: undefined,
            showPresetCreation: false,
            newPresetName: undefined,
            errorMessage: undefined
        };
    },
    computed: {
        generatedPresetName() {
            let name = `${this.currentMode.name} control - Frame ${this.currentFrame}`;
            if (this.currentMode.id === 2) {
                name = `${this.currentStyle.bands.length} channels`;
            } else if (this.currentMode.id === 3) {
                name = `${this.currentStyle.bands.length} bands`;
            }
            return name;
        },
        availablePresets() {
            return this.itemPresets.concat(this.folderPresets);
        }
    },
    watch: {
        newPresetName() {
            if (this.newPresetName) {
                this.errorMessage = undefined;
            }
        },
        selectedPreset() {
            if (this.selectedPreset) {
                const preset = this.availablePresets.find((p) => p.name === this.selectedPreset);
                if (preset.mode && preset.mode.id !== undefined) {
                    this.$emit('setCurrentMode', preset.mode);
                }
                if (preset.frame !== undefined) {
                    this.$emit('setCurrentFrame', preset.frame);
                }
                if (preset.style && preset.style.bands.length) {
                    const styleArray = this.styleFromPreset(preset);
                    this.$emit('updateStyle', preset.mode.id, {bands: styleArray, preset: true});
                }
            }
        },
        currentMode() {
            this.checkPresetMatch();
        },
        currentFrame() {
            this.checkPresetMatch();
        },
        currentStyle() {
            this.checkPresetMatch();
        }
    },
    mounted() {
        this.getPresets();
    },
    methods: {
        presetApplicable(preset) {
            if (this.itemPresets.find((p) => p.name === preset.name)) {
                // preset with this name already exists on the item,
                // prefer the item preset; don't show both
                return false;
            } else if (
                parseInt(preset.frame) >= (this.imageMetadata.frames || [null]).length ||
                !this.availableModes.includes(preset.mode.id)
            ) {
                return false;
            } else if (preset.style && preset.style.bands) {
                if (preset.mode.id === 2) {
                    // Channel compositing, compare to num channels
                    if (this.imageMetadata.IndexRange &&
                        this.imageMetadata.IndexRange.IndexC &&
                        preset.style.bands.some((b) => b.framedelta >= this.imageMetadata.IndexRange.IndexC)
                    ) {
                        return false;
                    }
                } else if (preset.mode.id === 3) {
                    // Band compositing, compare to num bands
                    if (this.imageMetadata.bandCount &&
                        preset.style.bands.some((b) => b.band >= this.imageMetadata.bandCount)
                    ) {
                        return false;
                    }
                }
            }

            return true;
        },
        getPresets() {
            girder.rest.restRequest({
                type: 'GET',
                url: 'item/' + this.itemId + '/internal_metadata/presets'
            }).then((presets) => {
                if (presets) {
                    this.itemPresets = presets;
                }
                if (this.liConfig && this.liConfig.imageFramePresets) {
                    this.folderPresets = this.liConfig.imageFramePresets.filter(this.presetApplicable);
                    if (this.liConfig.imageFramePresetDefaults) {
                        this.liConfig.imageFramePresetDefaults.every(({name}) => {
                            const presetMatch = this.folderPresets.find((p) => p.name === name);
                            if (presetMatch) {
                                // found applicable preset in defaults list
                                // set as selected then return
                                this.selectedPreset = name;
                                return false;
                            }
                            return true;
                        });
                    }
                }
                return undefined;
            });
        },
        addPreset(e, overwrite = false) {
            const newPreset = {
                name: this.newPresetName || this.generatedPresetName,
                mode: this.currentMode,
                frame: this.currentFrame,
                style: {bands: this.currentStyle.bands.map((b) => this.styleToAutoRange(b))}
            };
            newPreset.name = newPreset.name.trim();
            if (!overwrite && this.availablePresets.find((p) => p.name === newPreset.name)) {
                this.errorMessage = `There is already a preset named "${newPreset.name}". Overwrite "${newPreset.name}"?`;
            } else {
                this.itemPresets = this.itemPresets.filter((p) => p.name !== newPreset.name);
                this.itemPresets.push(newPreset);
                this.selectedPreset = newPreset.name;
                this.savePresetsList();
                this.newPresetName = undefined;
                this.errorMessage = undefined;
                this.showPresetCreation = false;
            }
        },
        deleteSelectedPreset() {
            this.itemPresets = this.itemPresets.filter((p) => p.name !== this.selectedPreset);
            this.selectedPreset = undefined;
            this.savePresetsList();
        },
        savePresetsList() {
            girder.rest.restRequest({
                type: 'PUT',
                url: 'item/' + this.itemId + '/internal_metadata/presets',
                data: JSON.stringify(this.itemPresets),
                contentType: 'application/json'
            });
        },
        styleToAutoRange(band) {
            band = Object.assign({}, band); // new reference
            if (band.min && band.min.toString().includes('min:')) {
                band.autoRange = parseFloat(band.min.replace('min:', '')) * 100;
                delete band.min;
                delete band.max;
            }
            return band;
        },
        styleFromAutoRange(band) {
            band = Object.assign({}, band); // new reference
            if (band.autoRange) {
                band.min = `min:${band.autoRange / 100}`;
                band.max = `max:${band.autoRange / 100}`;
                delete band.autoRange;
            }
            return band;
        },
        styleFromPreset(preset) {
            if (preset.style && preset.style.bands.length) {
                const styleArray = [];
                preset.style.bands.forEach((layer) => {
                    const styleEntry = {
                        min: layer.autoRange !== undefined ? `min:${layer.autoRange / 100}` : parseInt(layer.min),
                        max: layer.autoRange !== undefined ? `max:${layer.autoRange / 100}` : parseInt(layer.max),
                        palette: layer.palette,
                        framedelta: layer.framedelta,
                        band: layer.band
                    };
                    if (!styleEntry.min) delete styleEntry.min;
                    if (!styleEntry.max) delete styleEntry.max;
                    styleArray.push(styleEntry);
                });
                return styleArray;
            }
        },
        styleEqual(style1, style2) {
            if (style1 === style2) {
                return true;
            }
            if (style1.length !== style2.length) {
                return false;
            }
            return style1.every((b1) => {
                b1 = this.styleFromAutoRange(b1);
                let b2 = style2.find((b) => b.framedelta === b1.framedelta && b.band === b1.band);
                if (b2) {
                    b2 = this.styleFromAutoRange(b2);
                    return (
                        b1.min === b2.min &&
                        b1.max === b2.max &&
                        b1.palette === b2.palette
                    );
                } else return false;
            });
        },
        checkPresetMatch() {
            if (this.currentStyle) {
                const match = this.availablePresets.find((p) => (
                    p.mode.id === this.currentMode.id &&
                    p.frame === this.currentFrame &&
                    this.styleEqual(this.currentStyle.bands, this.styleFromPreset(p))
                ));
                this.selectedPreset = match ? match.name : undefined;
            }
        }
    }
};
</script>

<template>
  <div class="presets-menu">
    Image View Presets:
    <select v-model="selectedPreset">
      <option
        v-if="availablePresets.length === 0"
        :value="undefined"
        selected
        disabled
      >
        No presets available
      </option>
      <option
        v-else
        :value="undefined"
        selected
        disabled
      >
        Select a preset
      </option>
      <option
        v-for="preset in availablePresets"
        :key="preset.id"
      >
        {{ preset.name }}
      </option>
    </select>
    <i
      v-if="selectedPreset"
      class="icon-trash"
      @click="deleteSelectedPreset"
    />
    <i
      class="icon-plus"
      @click="showPresetCreation = !showPresetCreation"
    />
    <div
      v-if="showPresetCreation"
      class="preset-creation"
    >
      Save Current State as New Preset:
      <input
        v-model="newPresetName"
        :placeholder="generatedPresetName"
      >
      <span class="red--text">{{ errorMessage }}</span>
      <button
        v-if="errorMessage === undefined"
        @click="addPreset"
      >
        Save Preset
      </button>
      <button
        v-else
        @click="(e) => addPreset(e, true)"
      >
        Update Preset
      </button>
    </div>
  </div>
</template>

<style scoped>
.presets-menu {
    float: right;
    text-align: right;
}
.preset-creation {
    display: flex;
    flex-direction: column;
    align-items: end;
    padding-top: 5px;
}
.red--text {
    color: red;
    max-width: 250px;
}
</style>
