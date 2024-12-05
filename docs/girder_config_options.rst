Girder Configuration Options
============================

General Plugin Settings
-----------------------

There are some general plugin settings that affect large_image as a Girder plugin.  These settings can be accessed by an Admin user through the ``Admin Console`` / ``Plugins`` and selecting the gear icon next to ``Large image``.

YAML Configuration Files
------------------------

Some settings can be specified per-folder tree using yaml files.  For these settings, if the configuration file exists in the current folder it is used.  If not, the parent folders are checked iteratively up to the parent collection or user.  If no configuration file is found, the ``.config`` folder in the collection or user is checked for the file.  Lastly, the ``Configuration Folder`` specified on the plugin settings page is checked for the configuration file.

The configuration files can have different configurations based on the user's access level and group membership.

The yaml file has the following structure:

::

    ---
    # most settings are key-value pairs, where the value could be another
    # dictionary with keys and values, lists, or other valid data.
    <key>: <value>
    # The access key is special
    access:
      # logged in users get these settings
      user:
        # If the value is a dictionary and the key matches a key at the base
        # level, then the values are combined.  To completely replace the base
        # value, add the special key "__all__" and set it's value to true.
        <key>: <value>
      # admin users get these settings
      admin:
        <key>: <value>
    # The groups key specifies that specific user groups have distinct settings
    groups:
      <group name>:
        <key>: <value>
        # groups can specify access based on user or admin, too.
        access: ...
    # The users key specifies that a specific user has distinct settings
    users:
      <user login>:
        <key>: <value>
    # If __inherit__ is true, then merge this config file with the next config
    # file in the parent folder hierarchy.
    __inherit__: true

.large_image_config.yaml
~~~~~~~~~~~~~~~~~~~~~~~~

Item Lists
..........

This is used to specify how items appear in item lists.  There are two settings, one for folders in the main Girder UI and one for folders in dialogs (such as when browsing in the file dialog).

::

    ---
    # If present, show a table with column headers in item lists
    itemList:
      # layout does not need to be specified.
      layout:
        # The default list (with flatten: false) shows only the items in the
        # current folder; flattening the list shows items in the current folder
        # and all subfolders.  This can also be "only", in which case the
        # flatten option will start enabled and, when flattened, the folder
        # list will be hidden.
        flatten: true
        # The default layout is a list.  This can optionally be "grid"
        mode: grid
        # max-width is only used in grid mode.  It is the maximum width in
        # pixels for grid entries.  It defaults to 250.
        max-width: 250
      # group does not need to be specified.  Instead of listing items
      # directly, multiple items can be grouped  together.
      group:
        # keys is a single metadata value reference (see the column metadata
        # records), or a list of such records.
        keys: dicom.PatientID
        # counts is optional.  If specified, the left side is either a metadata
        # value references or "_id" to just count total items.  The right side
        # is where, conceptually, the count is stored in the item.meta record.
        # to show a column of the counts, add a metadata column with a value
        # equal to this.  That is, in this example, all items with the same
        # meta.dicom.PatientID are grouped as a single row, and two count
        # columns are generated.  The unique values for each group row of
        # meta.dicom.StudyInstanceUID and counted and that count is added to
        # meta._count.studiescount.
        counts:
          dicom.StudyInstanceUID: _count.studiescount
          dicom.SeriesInstanceUID: _count.seriescount
      # navigate does nto need to be specified.  It changes the behavior of
      # clicking on an item from showing the item page to another action.
      navigate:
        # type can be "item": the default, open the item page, "itemList": go
        # to the named item page, or "open" to open an application
        type: itemList
        # if the type is "itemList", the name is the name of the itemList to
        # display.  If the type is "open", the name is the name of the
        # registered  application that should be opened by preference (e.g.,
        # "histomicsui" or "volview").  If that application does not report it
        # can open the item or no name is specified, the highest priority
        # application that can open the item will be used.
        name: studyList
      # show these columns in order from left to right.  Each column has a
      # "type" and "value".  It optionally has a "title" used for the column
      # header, and a "format" used for searching and filtering.  The "label",
      # if any, is displayed to the left of the column value.  This is more
      # useful in an grid view than in a column view.
      columns:
        -
          # The "image" type's value is either "thumbnail" or the name of an
          # associated image, such as "macro" or "label".
          type: image
          value: thumbnail
          title: Thumbnail
          # The maximum size of images can be specified.  It defaults to 160 x
          # 100.  It will always maintain the original aspect ratio.
          width: 250
          height: 250
        -
          type: image
          value: label
          title: Slide Label
        -
          # The "record" type is from the default item record.  The value is
          # one of "name", "description", "created", "updated", "size", or
          # "controls".
          type: record
          value: name
        -
          type: record
          value: size
        -
          type: record
          value: controls
        -
          # The "metadata" type is taken from the item's "meta" contents.  It
          # can be a nested key by using dots in its name.
          type: metadata
          value: Stain
          # "format" can be "text", "number", "category", "datetime", "date",
          # "time".  "datetime", "date", and "time" use the user's browser's
          # locale to convert the date and/or time to their browser's preferred
          # format.  Other values may be specified later.
          format: text
        -
          type: metadata
          # This will get "Label" from the first entry in array "gloms"
          value: gloms.0.Label
          title: First Glom Label
        -
          type: metadata
          # You can use some javascript-like properties, such as .length for
          # the length of arrays.
          value: gloms.length
          title: Number of Gloms
          # You can have this value be populated for just some of the items by
          # specifying an "only" list.  Each entry in the only list must have
          # the "type" and "value" as per the column it is filtering on, plus a
          # "match" value that is used as a case-insensitive RegExp.  All such
          # limits must match to show the value.
          only:
            -
              type: record
              value: name
              # only show this for items whose names end with ".svs".
              match: "\\.svs$"
        # You can edit metadata in a item list by adding the edit: true entry
        # and the options from the itemMetadata records that are detailed
        # below.  In this case, edits to metadata that validate are saved
        # immediately.
        -
          type: metadata
          value: userstain
          title: User Stain
          label: User Stain
          edit: true
          # description is used as both a tooltip and as placeholder text
          description: Staining method
          # if required is true, the value can't be empty
          required: true
          # If a regex is specified, the value must match
          # regex: '^(Eosin|H&E|Other)$'
          # If an enum is specified, the value is set via a dropdown select box
          enum:
            - Eosin
            - H&E
            - Other
          # If a default is specified, if the value is unset, it will show this
          # value in the control
          default: H&E
      defaultSort:
        # The default lists a sort order for sortable columns.  This must have
        # type, value, and dir for each entry, where dir is either "up" or
        # "down".
        -
          type: metadata
          value: Stain
          dir: up
        -
          type: record
          value: name
          dir: down
    itemListDialog:
      # Show these columns
      columns:
        -
          type: image
          value: thumbnail
          title: Thumbnail
        -
          type: record
          value: name
        -
          type: metadata
          value: Stain
          format: text
        -
          type: record
          value: size

If there are no large images in a folder, none of the image columns will appear.

Named Item Lists
................

Multiple item lists can be stored with specific names.  A default item list can be specified.

::

    ---
    # If present and the value is a key in the namedItemLists section, that
    # list will be shown unless the URL routes to a different list.
    defaultItemList: images
    # Any number of items can be in the namedItemLists section.  Each name
    # must be distinct.  The system can show the specific list by routing to
    # ?namedList=<name> as part of the url after the folder id.
    namedItemLists:
      image:
        layout:
          mode: list
        columns:
          -
            type: image
            value: thumbnail
            title: Thumbnail
          -
            type: image
            value: label
            title: Slide Label
          -
            # The "record" type is from the default item record.  The value is
            # one of "name", "size", or "controls".
            type: record
            value: name
          -
            type: record
            value: size
          -
            type: record
            value: controls

Item Metadata
.............

By default, item metadata can contain any keys and values.  These can be given better titles and restricted in their data types.

::

    ---
    # If present, offer to add these specific keys and restrict their datatypes
    itemMetadata:
      -
        # value is the key name within the metadata
        value: stain
        # title is the displayed titles
        title: Stain
        # description is used as both a tooltip and as placeholder text
        description: Staining method
        # if required is true, the delete button does not appear
        required: true
        # If a regex is specified, the value must match
        # regex: '^(Eosin|H&E|Other)$'
        # If an enum is specified, the value is set via a dropdown select box
        enum:
          - Eosin
          - H&E
          - Other
        # If a default is specified, when the value is created, it will show
        # this value in the control
        default: H&E
      -
        value: rating
        # type can be "number", "integer", or "text" (default)
        type: number
        # minimum and maximum are inclusive
        minimum: 0
        maximum: 10
        # Exclusive values can be specified instead
        # exclusiveMinimum: 0
        # exclusiveMaximum: 10


Image Frame Presets
....................

This is used to specify a list of presets for viewing images in the folder.
Presets can be customized and saved in the GeoJS Image Viewer.
To retrieve saved presets, use ``[serverURL]/api/v1/item/[itemID]/internal_metadata/presets``.
You can convert the response to YAML and paste it into the ``imageFramePresets`` key in your config file.

Each preset can specify a name, a view mode, an image frame, and style options.

- The name of a preset can be any string which uniquely identifies the preset.

- There are four options for mode:

  - Frame control

    - id: 0
    - name: Frame

  - Axis control

    - id: 1
    - name: Axis

  - Channel Compositing

    - id: 2
    - name: Channel Compositing

  - Band Compositing

    - id: 3
    - name: Band Compositing

- The frame of a preset is a 0-based index representing a single frame in a multiframe image.
  For single-frame images, this value will always be 0.
  For channel compositing, each channel will have a ``framedelta`` value which represents distance from this base frame value.
  The result of channel compositing is multiple frames (calculated via framedelta) composited together.

- The style of a preset is a dictionary with a schema similar to the [style schema for tile retrieval](tilesource_options.rst#style). The value for a preset's style consists of a band definition, where each band may have the following:

  - ``band``: A 1-based index of a band within the current frame
  - ``framedelta``: An integer representing distance from the current frame, used for compositing multiple frames together
  - ``palette``: A hexadecimal string beginning with "#" representing a color to stain this frame
  - ``min``: The value to map to the first palette value
  - ``max``: The value to map to the last palette value
  - ``autoRange``: A shortcut for excluding a percentage from each end of the value distribution in the image. Express as a float.

The YAML below includes some example presets.

::

    ---
    # If present, each preset in this list will be added to the preset list
    # of every image in the folder for which the preset is applicable
    imageFramePresets:
    - name: Frame control - Frame 4
      frame: 4
      mode:
        id: 0
        name: Frame
    - name: Axis control - Frame 25
      frame: 25
      mode:
        id: 1
        name: Axis
    - name: 3 channels
      frame: 0
      mode:
        id: 2
        name: Channel Compositing
      style:
        bands:
        - framedelta: 0
          palette: "#0000FF"
        - framedelta: 1
          palette: "#FF0000"
        - framedelta: 2
          palette: "#00FF00"
    - name: 3 bands
      frame: 0
      mode:
        id: 3
        name: Band Compositing
      style:
        bands:
        - band: 1
          palette: "#0000FF"
        - band: 2
          palette: "#FF0000"
        - band: 3
          palette: "#00FF00"
    - name: Channels with Min and Max
      frame: 0
      mode:
        id: 2
        name: Channel Compositing
      style:
        bands:
        - min: 18000
          max: 43000
          framedelta: 0
          palette: "#0000FF"
        - min: 18000
          max: 43000
          framedelta: 1
          palette: "#FF0000"
        - min: 18000
          max: 43000
          framedelta: 2
          palette: "#00FF00"
        - min: 18000
          max: 43000
          framedelta: 3
          palette: "#FFFF00"
    - name: Auto Ranged Channels
      frame: 0
      mode:
        id: 2
        name: Channel Compositing
      style:
        bands:
        - autoRange: 0.2
          framedelta: 0
          palette: "#0000FF"
        - autoRange: 0.2
          framedelta: 1
          palette: "#FF0000"
        - autoRange: 0.2
          framedelta: 2
          palette: "#00FF00"
        - autoRange: 0.2
          framedelta: 3
          palette: "#FFFF00"
        - autoRange: 0.2
          framedelta: 4
          palette: "#FF00FF"
        - autoRange: 0.2
          framedelta: 5
          palette: "#00FFFF"
        - autoRange: 0.2
          framedelta: 6
          palette: "#FF8000"


Image Frame Preset Defaults
...........................
This is used to specify a list of preset defaults, in order of precedence.
These presets are to be automatically applied to an image in this folder if they are applicable.
In the case that a preset is not applicable to an image, the next item in this list will be used.

** Important: the presets named in this list must have corresponding entries in the ``imageFramePresets`` configuration, else this configuration will have no effect. **

::

    ---
    # The preset named "Primary Preset" will be applied to all images in this folder.
    # Any images for which "Primary Preset" does not apply will have "Secondary Preset" applied.
    # Any images for which neither "Primary Preset" nor "Secondary Preset" apply will have "Tertiary Preset" applied.
    imageFramePresetDefaults:
    - name: Primary Preset
    - name: Secondary Preset
    - name: Tertiary Preset

::

    ---
    # This example would be used with the example for ``imageFramePresets`` shown above.
    # Images with 7 or more channels would use "Auto Ranged Channels"
    # Images with fewer than 7 but at least 4 channels would use "Channels with Min and Max"
    # Images with 3 channels would use "3 channels"
    # Images with fewer than 3 channels would not have a default preset applied.
    imageFramePresetDefaults:
    - name: Auto Ranged Channels
    - name: Channels with Min and Max
    - name: 3 channels



Editing Configuration Files
---------------------------

Some file types can be edited on their item page.  This is detected based on the mime type associated with the file: ``application/json`` for json files and ``text/yaml`` or ``text/x-yaml`` for yaml files.  If a user has enough permissions, these can be modified and saved.  Note that this does not alter imported files; rather, on save it will create a new file in the assetstore and use that; this works fine for using the configuration files.

For admins, there is also support for the ``application/x-girder-ini`` mime type for Girder configuration files.   This has a special option to replace the existing Girder configuration and restart the server and should be used with due caution.
