import large_image
from pathlib import Path
from format_examples_datastore import EXAMPLES_FOLDER, format_examples, fetch_all


TABLE_FILE = Path('./format_table.rst')
NO_MULTIFRAME_SOURCES = ['deepzoom', 'openjpeg', 'openslide']


def evaluate_examples():
    large_image.tilesource.loadTileSources()
    available_tilesources = large_image.tilesource.AvailableTileSources
    results = []
    for format_data in format_examples:
        name = format_data.get('name')
        long_name = format_data.get('long_name')
        reference = format_data.get('reference')
        for example in format_data.get('examples', []):
            skip = example.get('skip')
            if not skip:
                filename = example.get('filename')
                url = example.get('url')
                extension = filename.split('.')[-1]
                filepath = Path(EXAMPLES_FOLDER, filename)
                print(f'Evaluating {filename}. ')
                for tilesource_name, readable in large_image.canReadList(filepath):
                    tilesource = available_tilesources.get(tilesource_name)
                    if readable and tilesource:
                        try:
                            s = tilesource(filepath)
                            results.append(
                                dict(
                                    name=name,
                                    long_name=long_name,
                                    reference=reference,
                                    extension=extension,
                                    filename=filename,
                                    url=url,
                                    tilesource=tilesource_name,
                                    multiframe=(
                                        False if tilesource_name in NO_MULTIFRAME_SOURCES else
                                        True if s.getMetadata().get('frames') is not None else
                                        'Unknown'
                                    ),
                                    geospatial=hasattr(s, 'projection'),
                                    write=hasattr(s, 'addTile'),
                                    associated=(
                                        s.getAssociatedImagesList is not
                                        large_image.tilesource.FileTileSource.getAssociatedImagesList
                                    ),
                                ),
                            )
                        except large_image.exceptions.TileSourceError:
                            pass
    return results


def combine_rows(results):
    # combine rows that only differ on tilesource
    table_rows = {}
    for result in results:
        row_base_key = result.get('extension')
        row_key_index = 0
        row_key = f'{row_base_key}_{row_key_index}'
        # if this source has "maybe" for multiframe
        # and another source has True, change multiframe value to False
        if (
            isinstance(result['multiframe'], str) and
            any(
                r['extension'] == result['extension'] and
                r['multiframe'] and isinstance(r['multiframe'], bool)
                for r in results
            )
        ):
            result['multiframe'] = False
        while row_key in table_rows:
            if all(
                value == table_rows[row_key][key]
                for key, value in result.items()
                if key != 'tilesource'
            ):
                if not isinstance(table_rows[row_key]['tilesource'], list):
                    table_rows[row_key]['tilesource'] = [
                        table_rows[row_key]['tilesource'],
                    ]
                table_rows[row_key]['tilesource'] = [
                    *table_rows[row_key]['tilesource'],
                    result['tilesource'],
                ]
                break
            else:
                row_key_index += 1
                row_key = f'{row_base_key}_{row_key_index}'
        if row_key not in table_rows:
            table_rows[row_key] = result
    return table_rows


def generate():
    fetch_all()
    results = evaluate_examples()
    table_rows = combine_rows(results)

    # generate RST-formatted table
    columns = [
        dict(label='Format', key='name'),
        dict(label='Extension', key='extension'),
        dict(label='Tile Source', key='tilesource'),
        dict(label='Multiframe', key='multiframe'),
        dict(label='Geospatial', key='geospatial'),
        dict(label='Writeable', key='write'),
        dict(label='Associated Images', key='associated'),
        dict(label='Example File', key='url'),
    ]
    lines = [
        '.. list-table:: Common Formats',
        '   :header-rows: 1',
        '',
    ]
    for index, col in enumerate(columns):
        label = col.get('label')
        if index == 0:
            lines.append(f'   * - {label}')
        else:
            lines.append(f'     - {label}')
    for row_key, row in table_rows.items():
        lines.append('')  # blank line for ref separation
        lines.append(f'       .. _{row_key}:')
        for index, col in enumerate(columns):
            col_key = col.get('key')
            col_value = row.get(col_key)
            if col_key == 'extension':
                # format extensions with monospace font
                col_value = f'``{col_value}``'
            elif col_key == 'name':
                # include reference as link and long name as tooltip
                reference_link = row.get('reference')
                long_name = row.get('long_name')
                if long_name:
                    col_value = f':abbr:`{col_value} ({long_name})`'
                if reference_link:
                    col_value = f'{col_value} (`spec <{reference_link}>`__)'
            elif col_key == 'url':
                # reformat example download link
                col_value = (
                    f'`Download <{col_value}>`__'
                )
            elif col_key == 'tilesource':
                # join tilesource lists with commas
                if isinstance(col_value, list):
                    col_value = ', '.join(col_value)

            if index == 0:
                lines.append(f'   * - {col_value} :ref:`🔗 <{row_key}>`')
            else:
                lines.append(f'     - {col_value}')
    lines.append('')
    with open(TABLE_FILE, 'w') as f:
        f.write('\n'.join(lines))
    print('Wrote format table at', str(TABLE_FILE))


if __name__ == '__main__':
    generate()
