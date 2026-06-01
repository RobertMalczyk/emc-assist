# UI and interactive recommendations

## MVP

No full UI. A Markdown report plus JSON recommendations.

## V1 Pro

- local web UI or desktop,
- list of recommendations,
- component panel,
- variant selection,
- "simulate variant" button,
- before / after comparison,
- report export.

## Graphical display of changes

Target state:

- baseline schematic,
- suggestion overlay,
- risk coloring,
- click on an element,
- value selection,
- accept / reject a change.

## Caveat

Automatic editing of `.asc` is risky. Initially the safer path is:

- do not modify the original,
- generate a separate testbench,
- generate a patch / recommendation,
- only later build an `.asc` modifier.
