<script>
export default {
    name: 'CompositeLayers',
    props: [
        'itemId',
        'currentFrame',
        'currentStyle',
        'histogramParamStyle',
        'frameHistograms',
        'getFrameHistogram',
        'layers',
        'layerMap',
        'active',
        'colors',
        'styleUpdate'
    ],
    data() {
        return {
            enabledLayers: [],
            compositeLayerInfo: {},
            expandedRows: [],
            autoRangeForAll: undefined,
            showKeyboardShortcuts: false
        };
    },
    computed: {
        histogramParams() {
            return {
                frame: this.currentFrame,
                width: 1024,
                height: 1024,
                bins: 512,
                resample: false,
                style: this.histogramParamStyle,
                roundRange: true
            };
        }
    },
    watch: {
        active() {
            if (this.active) {
                document.addEventListener('keydown', this.keyHandler);
            } else {
                document.removeEventListener('keydown', this.keyHandler);
            }
        },
        currentStyle() {
            if (this.currentStyle.preset) {
                this.initializeStateFromStyle();
            }
        },
        histogramParams() {
            this.getFrameHistogram(this.histogramParams);
        }
    },
    mounted() {
        this.initializeLayerInfo();
        if (this.currentStyle) {
            this.initializeStateFromStyle();
        } else {
            if (this.layerMap) {
                // channels all enabled by default
                this.enabledLayers = this.layers;
            } else {
                // only some bands enabled by default
                ['red', 'green', 'blue', 'gray', 'grey'].forEach((bandColor) => {
                    if (this.layers.includes(bandColor)) {
                        this.enabledLayers.push(bandColor);
                    }
                });
                // if no known band colors exist, enable the first three
                if (this.enabledLayers.length === 0) {
                    this.enabledLayers = this.layers.slice(0, 3);
                }
            }
            this.updateActiveLayers();
            this.updateStyle();
        }
        if (this.active) {
            document.addEventListener('keydown', this.keyHandler);
        }
    },
    methods: {
        keyHandler(e) {
            let numericKey = parseFloat(e.key);
            if (e.ctrlKey && !isNaN(numericKey)) {
                e.preventDefault();
                if (numericKey === 0) {
                    numericKey += 10;
                }
                if (e.altKey) {
                    numericKey += 10;
                }
                const layerIndex = numericKey - 1;
                if (layerIndex < this.layers.length) {
                    const targetLayer = this.layers[layerIndex];
                    if (this.compositeLayerInfo[targetLayer].enabled) {
                        this.enabledLayers = this.enabledLayers.filter((v) => v !== targetLayer);
                    } else {
                        this.enabledLayers.push(targetLayer);
                    }
                    this.updateActiveLayers();
                }
            }
        },
        initializeLayerInfo() {
            const usedColors = [];
            this.compositeLayerInfo = {};
            this.layers.forEach((layerName, i) => {
                this.compositeLayerInfo[layerName] = {
                    layerName,
                    index: i,
                    framedelta: this.layerMap ? this.layerMap[layerName] : undefined,
                    band: this.layerMap ? undefined : i + 1, // expected 1-based index
                    enabled: true,
                    min: undefined,
                    max: undefined,
                    autoRange: undefined
                };
            });
            // Assign colors
            this.layers.forEach((layerName) => {
                if (!this.compositeLayerInfo[layerName].palette) {
                    const channelColor = this.getChannelColor(layerName, usedColors);
                    if (channelColor) {
                        this.compositeLayerInfo[layerName].palette = channelColor;
                    }
                }
            });
            this.layers.forEach((layerName) => {
                if (!this.compositeLayerInfo[layerName].palette) {
                    let chosenColor;
                    const unusedColors = this.colors.other.filter(
                        (color) => !usedColors.includes(color)
                    );
                    if (unusedColors.length > 0) {
                        chosenColor = unusedColors[0];
                    } else {
                        chosenColor = this.colors.other[Math.floor(Math.random() * this.colors.other.length)];
                    }
                    this.compositeLayerInfo[layerName].palette = chosenColor;
                    usedColors.push(chosenColor);
                }
            });
            this.getFrameHistogram(this.histogramParams);
        },
        initializeStateFromStyle() {
            this.enabledLayers = [];
            this.layers.forEach((layer) => {
                const layerInfo = this.compositeLayerInfo[layer];
                const currentLayerStyle = this.currentStyle.bands.find(
                    (s) => s.framedelta === layerInfo.framedelta &&
                        s.band === layerInfo.band
                );
                if (currentLayerStyle) {
                    this.enabledLayers.push(layer);
                    this.compositeLayerInfo[layer].enabled = true;
                    this.compositeLayerInfo[layer].palette = currentLayerStyle.palette;
                    this.compositeLayerInfo[layer].min = currentLayerStyle.min;
                    this.compositeLayerInfo[layer].max = currentLayerStyle.max;
                    if (
                        currentLayerStyle.min && currentLayerStyle.max &&
                        currentLayerStyle.min.toString().includes('min:') &&
                        currentLayerStyle.max.toString().includes('max:')
                    ) {
                        this.compositeLayerInfo[layer].autoRange = parseFloat(
                            currentLayerStyle.min.toString().replace('min:', '')
                        ) * 100;
                        this.compositeLayerInfo[layer].min = undefined;
                        this.compositeLayerInfo[layer].max = undefined;
                    } else {
                        this.compositeLayerInfo[layer].autoRange = undefined;
                    }
                } else {
                    this.compositeLayerInfo[layer].enabled = false;
                    this.compositeLayerInfo[layer].autoRange = undefined;
                    this.compositeLayerInfo[layer].min = undefined;
                    this.compositeLayerInfo[layer].max = undefined;
                }
            });

            const autoRanges = Object.entries(this.compositeLayerInfo)
                .filter(([index, info]) => info.enabled)
                .map(([index, info]) => info.autoRange);
            if (autoRanges.every((v) => v === autoRanges[0])) {
                this.autoRangeForAll = autoRanges[0];
            } else {
                this.autoRangeForAll = undefined;
            }
        },
        toggleEnableAll() {
            if (!this.layers.every((l) => this.enabledLayers.includes(l))) {
                this.enabledLayers = this.layers;
            } else {
                this.enabledLayers = [];
            }
            this.updateActiveLayers();
        },
        toggleExpanded(index) {
            if (this.expandedRows.includes(index)) {
                this.expandedRows = this.expandedRows.filter((v) => v !== index);
            } else {
                this.expandedRows = [...this.expandedRows, index];
            }
        },
        toggleAllExpanded() {
            if (this.expandedRows.length === this.layers.length) {
                this.expandedRows = [];
            } else {
                this.expandedRows = Object.values(this.compositeLayerInfo).map(({index}) => index);
            }
        },
        updateLayerAutoRange(layer, value) {
            this.compositeLayerInfo = Object.assign(
                {}, this.compositeLayerInfo,
                {
                    [layer]: Object.assign(
                        {}, this.compositeLayerInfo[layer], {autoRange: value}
                    )
                }
            );
            this.updateStyle();
        },
        updateAllAutoRanges(value) {
            this.autoRangeForAll = value;
            this.compositeLayerInfo = Object.fromEntries(
                Object.entries(this.compositeLayerInfo).map(([layerName, layerInfo]) => {
                    return [
                        layerName,
                        Object.assign({}, layerInfo, {autoRange: value})
                    ];
                })
            );
            this.updateStyle();
        },
        allAutoRange() {
            return Object.values(this.compositeLayerInfo).every(({autoRange}) => autoRange !== undefined);
        },
        updateLayerColor(layer, event) {
            this.compositeLayerInfo[layer].palette = event.target.value;
            this.updateStyle();
        },
        updateLayerMin(layer, newVal) {
            const newMinVal = Number.isFinite(newVal) ? parseFloat(newVal) : undefined;
            this.compositeLayerInfo[layer].min = newMinVal;
            this.compositeLayerInfo = Object.assign({}, this.compositeLayerInfo); // for reactivity
            this.updateStyle();
        },
        updateLayerMax(layer, newVal) {
            const newMaxVal = Number.isFinite(newVal) ? parseFloat(newVal) : undefined;
            this.compositeLayerInfo[layer].max = newMaxVal;
            this.compositeLayerInfo = Object.assign({}, this.compositeLayerInfo); // for reactivity
            this.updateStyle();
        },
        updateActiveLayers() {
            this.layers.forEach((layer) => {
                this.compositeLayerInfo[layer].enabled = this.enabledLayers.includes(layer);
            });
            this.updateStyle();
        },
        updateStyle() {
            const activeLayers = Object.values(
                this.compositeLayerInfo
            ).filter((layer) => layer.enabled);
            const styleArray = [];
            activeLayers.forEach((layer) => {
                const styleEntry = {
                    min: layer.autoRange !== undefined ? `min:${layer.autoRange / 100}` : layer.min,
                    max: layer.autoRange !== undefined ? `max:${layer.autoRange / 100}` : layer.max,
                    palette: layer.palette,
                    framedelta: layer.framedelta,
                    band: layer.band
                };
                styleArray.push(styleEntry);
            });
            this.styleUpdate({bands: styleArray});
        },
        getChannelColor(name, usedColors) {
            // Search for case-insensitive regex match among known channel-colors
            for (const [channelPattern, color] of Object.entries(this.colors.channel)) {
                if (!usedColors.includes(color) && name.match(new RegExp(channelPattern, 'i'))) {
                    usedColors.push(color);
                    return color;
                }
            }
        }
    }
};
</script>

<template>
  <div>
    <i
      class="icon-keyboard fa fa-keyboard"
      @click="showKeyboardShortcuts = !showKeyboardShortcuts"
    ></i>
    <div
      v-if="showKeyboardShortcuts"
      class="shortcuts"
    >
      <div class="h5">
        Keyboard Shortcuts
      </div>
      <div>
        <span class="monospace">ctrl + number</span>
        Toggle visibility of the layer at the number position
      </div>
      <div>
        <span style="font-weight: bold;">Example: </span>
        <span class="monospace">ctrl + 1</span>
        Toggle visibility of the first layer in the table
      </div>
      <div>
        <span class="monospace">ctrl + alt + number</span>
        Toggle visibility of the layer at the position of the number plus 10
      </div>
      <div>
        <span style="font-weight: bold;">Example: </span>
        <span class="monospace">ctrl + alt + 1</span>
        Toggle visibility of the eleventh layer in the table
      </div>
    </div>
    <div class="table-container">
      <table
        id="composite-layer-table"
        class="table table-condensed"
      >
        <thead class="table-header">
          <tr>
            <th>
              <input
                type="checkbox"
                class="input-80"
                :checked="layers.every((l) => enabledLayers.includes(l))"
                @input="toggleEnableAll"
              >
            </th>
            <th><span class="small-text">Name</span></th>
            <th><span class="small-text">Color</span></th>
            <th>
              <div class="auto-range-col">
                <div class="auto-range-label">
                  <span
                    class="small-text"
                    style="text-align: left"
                  >
                    Auto Range
                  </span>
                  <label class="switch">
                    <span
                      :class="allAutoRange() ? 'onoff-slider checked' : 'onoff-slider'"
                      @click="() => updateAllAutoRanges(allAutoRange() ? undefined : 0.2)"
                    ></span>
                  </label>
                </div>
                <span
                  v-if="allAutoRange()"
                  class="percentage-input"
                >
                  <input
                    type="number"
                    class="input-80"
                    :max="50"
                    :min="0"
                    :step="0.1"
                    :value="autoRangeForAll"
                    @input="(e) => updateAllAutoRanges(e.target.value)"
                  >
                </span>
              </div>
              <i
                :class="expandedRows.length === layers.length ? 'expand-btn icon-up-open fa fa-angle-up' : 'expand-btn icon-down-open fa fa-angle-down'"
                @click="toggleAllExpanded"
              ></i>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="{
              layerName, index, palette,
              autoRange, min, max,
              framedelta
            } in Object.values(compositeLayerInfo)"
            :key="layerName"
            :class="expandedRows.includes(index) ? 'tall-row table-row' : 'table-row'"
          >
            <td class="enable-col">
              <input
                v-model="enabledLayers"
                type="checkbox"
                class="input-80"
                :value="layerName"
                @change="updateActiveLayers"
              >
            </td>
            <td class="name-col">
              {{ layerName }}
            </td>
            <td class="color-col">
              <input
                id="color_picker"
                class="picker"
                type="color"
                :value="palette"
                @input="(swatch) => {updateLayerColor(layerName, swatch)}"
              />
            </td>
            <td class="auto-range-col">
              <div class="auto-range-label">
                <label class="switch">
                  <span
                    :class="autoRange ? 'onoff-slider checked' : 'onoff-slider'"
                    @click="() => updateLayerAutoRange(layerName, autoRange ? undefined : 0.2)"
                  ></span>
                </label>
              </div>
              <span
                v-if="autoRange"
                class="percentage-input"
              >
                <input
                  type="number"
                  class="input-80"
                  :max="50"
                  :min="0"
                  :step="0.1"
                  :value="autoRange"
                  @input="(e) => updateLayerAutoRange(layerName, e.target.value)"
                >
              </span>
              <i
                :class="expandedRows.includes(index) ? 'expand-btn icon-up-open fa fa-angle-up' : 'expand-btn icon-down-open fa fa-angle-down'"
                @click="() => toggleExpanded(index)"
              ></i>
            </td>
            <td
              v-if="expandedRows.includes(index)"
              class="advanced-section"
            >
              <histogram-editor
                :item-id="itemId"
                :layer-index="index"
                :current-frame="currentFrame"
                :frame-histograms="frameHistograms"
                :get-frame-histogram="getFrameHistogram"
                :histogram-params="histogramParams"
                :framedelta="framedelta"
                :auto-range="autoRange"
                :current-min="min"
                :current-max="max"
                :active="active"
                :update-min="(v, d) => updateLayerMin(layerName, v, d)"
                :update-max="(v, d) => updateLayerMax(layerName, v, d)"
                :update-auto-range="(v) => updateLayerAutoRange(layerName, v)"
              />
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.current-color {
    display: inline-block;
    width: calc(100% - 10px);
    height: 25px;
    background-color: #000;
    cursor: pointer;
}
.picker{
    background-color: white;
    border: none;
    width: 100%
}
.table-header {
    position: sticky;
    top: 0px;
    background-color: white;
    z-index: 2;
    border-bottom: 3px solid !important;
}
.table-row {
    vertical-align: top;
    border-bottom: 1px solid !important;
    position: relative;
}
.table-row > td {
    border-top: none !important;
}
.small-text {
    font-size: 10px;
}
.tall-row {
    height: 80px !important;
}
.enable-col {
    width: 30px;
}
.name-col {
    width: 50%;
    word-break: break-all;
    font-size: inherit;
}
.color-col {
    width: 25%;
}
.auto-range-col {
    min-width: 250px;
    position: relative;
    display: flex;
    column-gap: 5px;
    align-items: center;
}
.auto-range-label {
    display: flex;
    flex-direction: column;
}
.switch {
  position: relative;
  display: inline-block;
  width: 55px;
  height: 20px;
  margin-top: 5px;
}
.onoff-slider {
  position: absolute;
  cursor: pointer;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: #ccc;
  -webkit-transition: .4s;
  transition: .4s;
  border-radius: 34px;
}
.onoff-slider.checked {
  background-color: #2196F3;
}
.onoff-slider:focus{
  box-shadow: 0 0 1px #2196F3;
}
.onoff-slider:before {
  position: absolute;
  content: "";
  height: 15px;
  width: 15px;
  left: 4px;
  bottom: 2px;
  background-color: white;
  -webkit-transition: .4s;
  transition: .4s;
  border-radius: 50%;
}
.onoff-slider.checked:before {
  -webkit-transform: translateX(32px);
  -ms-transform: translateX(32px);
  transform: translateX(32px);
}
.table-container {
    overflow-y: scroll;
    overflow-x: hidden;
    position: relative;
    max-height: 300px;
}
.table {
    border-collapse: collapse;
    width: 100%
}
.expand-btn {
    position: absolute;
    right: 10px;
    top: 5px;
}
.advanced-section {
    position: absolute;
    left: 0px;
    top: 30px;
    width: calc(100% - 10px);
    height: 40px;
}
.icon-keyboard {
    font-size: 20px;
}
.shortcuts {
    padding-bottom: 10px;
}
.monospace {
    font-family: monospace;
    background-color: rgba(0, 0, 0, 0.2);
    padding: 1px;
}
</style>

<style>
.input-80 {
    width: 80px
}
.percentage-input {
    position: relative;
    width: 80px;
}
.jupyter-widgets .percentage-input {
    margin-top: 5px;
}
.percentage-input::after {
    position: absolute;
    content: '%';
    left: 45px;
    top: 3px;
}
.jupyter-widgets .expand-btn {
    font-size: 20px;
    font-weight: 900 !important;
}
</style>
