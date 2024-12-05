Girder Annotation Configuration Options
=======================================

The ``large_image`` annotation plugin adds models to the Girder database for supporting annotating large images.  These annotations can be rendered on images.
Annotations can include polygons, points, image overlays, and other types (see :doc:`annotations`). Each annotation can have a label and metadata.
Additional user interface libraries allow other libraries (like HistomicsUI) to let a user interactively add and modify annotations.

General Plugin Settings
-----------------------

There are some general plugin settings that affect large_image annotation as a Girder plugin.  These settings can be accessed by an Admin user through the ``Admin Console`` / ``Plugins`` and selecting the gear icon next to ``Large image annotation``.

Store annotation history
~~~~~~~~~~~~~~~~~~~~~~~~

If ``Record annotation history`` is selected, whenever annotations are saved, previous versions are kept in the database.  This can greatly increase the size of the database.  The old versions of the annotations allow the API to be used to revent to previous versions or to audit changes over time.

.large_image_config.yaml
~~~~~~~~~~~~~~~~~~~~~~~~

This can be used to specify how annotations are listed on the item page.

::

    ---
    # If present, show a table with column headers in annotation lists
    annotationList:
      # show these columns in order from left to right.  Each column has a
      # "type" and "value".  It optionally has a "title" used for the column
      # header, and a "format" used for searching and filtering.  There are
      # always control columns at the left and right.
      columns:
        -
          # The "record" type is from the default annotation record.  The value
          # is one of "name", "creator", "created", "updatedId", "updated".
          type: record
          value: name
        -
          type: record
          value: creator
          # A format of user will print the user name instead of the id
          format: user
        -
          type: record
          value: created
          # A format of datetime, date, or time will use the browser's default
          # date and/or time format
          format: datetime
        -
          # The "metadata" type is taken from the annotations's
          # "annotation.attributes" contents.  It can be a nested key by using
          # dots in its name.
          type: metadata
          value: Stain
          # "format" can be "text", "number", "category".  Other values may be
          # specified later.
          format: text
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

These values can be combined with values from the base large_image plugin.
