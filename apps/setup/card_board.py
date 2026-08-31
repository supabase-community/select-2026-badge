"""The QWERTY name editor: `kbqwerty`'s board, with this app's header on it.

WHY QWERTY AND NOT THE GRID.  Owner ruling, 2026-08-17, and it goes AGAINST the
press-count evidence, which is worth stating plainly rather than burying: over
1000 held-out generated names the grid means 47.88 presses and this board 51.55,
and "SAM MEECH" costs 34 against 40.  The keyboard bench exists to answer
whether RECOGNITION beats presses, and the owner has answered it for this app.

WHAT COMES ACROSS UNCHANGED, because it is measured and this app has no business
re-deciding it: three iOS planes on a twenty-unit board (160/20 is exactly 8 px,
so every letter key is exactly 16 px with no rounding drift); the inverted
LATCHING shift, because a badge types a name so the letters are uppercase by
default and a latch charges one press per case change rather than one per
letter; `¢` in the slot the transcription gives `¥`, because `¥` advances 0 px
and inks 0 px in all 37 ROM faces and would be an empty cell the caret could
still land on; lettered SHIFT and DEL keys, because no arrow, triangle or
backspace glyph exists at any codepoint on this device.

WHAT THIS FILE ADDS, AND IT IS ONLY THE HEADER.  `kbqwerty` is a BENCH: its
header says QWERTY and counts presses, and its DONE clears the field in place so
another trial can be run.  This is a product: the header says what field is
being edited and how much room is left in it, and DONE commits the name and pops
to the menu.  The board, the caret, the planes, the layout tables and the cell
renderer are all the shipped ones.

THE ADOPTION, AND THE TRAP IT AVOIDS.  `kbqwerty_board` rebinds
`kb_shell.KeyboardView` to its own `PlaneView` at import time, so this module
subclasses `board.PlaneView` BY NAME rather than reaching through
`kb_shell.KeyboardView` -- naming the attribute would give a different class
depending on import order, which is the kind of bug that shows up as one wrong
plane on one badge.

`kbgrid` IS BYTE-FROZEN BY A SHA-256 TEST (`kb/tests/test_kb_sameness.py::
ControlTests`) because it is the control in a comparison the owner is still
running.  Nothing in this app may edit `shared/kb_shell.py`, `shared/ui.py`,
`shared/kb_seam.py` or `identity/badge/identity/identity_keyboard.py`; it may
only vendor them.  Adding a consumer to `scripts/sync_ui.py` moves no bytes.
"""

import card_model as model
import kbqwerty_board as board


# Left margin and caret width, in logical pixels before the resolution scale.
# `kb_shell`'s own numbers: the header and the board share a left edge and the
# board starts at x = 0, so 3 rather than the nametag's 6.
TEXT_X = 3
CARET_W = 2


class NameBoard(board.PlaneView):
    """`kbqwerty`'s three-plane view with a product header.

    Inherits the whole pixel layer: `_pixels` (integer arithmetic, so a row
    tiles seamlessly and cannot resolve differently in the browser than on the
    badge), `plane_cells` (one resolved table per plane, built once), `_cell`
    (bounded and ellipsed, because the renderer drops out-of-bounds glyphs
    silently), and the non-selectable A/B/C hint strip below the board.
    """

    def __init__(self, screen_api, image_api, color_api, font_api, rect_api):
        board.PlaneView.__init__(self, board, screen_api, image_api, color_api,
                                 font_api, rect_api)
        self.red = color_api.rgb(245, 80, 96)

    def draw(self, plan):
        """One frame, from the plan rather than from a bench app object.

        `board.publish` runs FIRST and before anything is drawn, because the
        module-level `ROWS`/`LAYOUT`/`CENTRES` mirror is what every reader of
        this board indexes into, and indexing plane 0's nine-cell row with a
        column from plane 1's ten-cell row is an IndexError -- a crash, not a
        wrong label.
        """
        editor = plan["board"]
        screen = self.screen
        chrome = self.chrome
        self.board.publish(editor.plane, editor.upper)
        self.cells = self.plane_cells[editor.plane]

        screen.pen = self.dark
        screen.clear()
        screen.font = chrome.font

        # THE FIELD'S NAME, not the board's.  A wearer who reached this screen
        # from a menu row called NAME needs to be told what they are typing
        # into, not which layout they are typing on.
        self._text("NAME", self.text_x, self.pad, self.accent)
        counter = "%d/%d" % (len(editor.text), editor.limit)
        self._text(counter, chrome.width - self.text_x - self._width(counter),
                   self.pad, self.red if editor.full() else self.grey)

        y = self.pad + self.step
        typed = editor.text
        # WHOSE CAP THIS IS, and it goes on the second row because the header
        # block is exactly TWO rows tall -- `kb_shell` fixes that height so a
        # board with a different row count cannot move the field, and a third
        # line here would be drawn straight over the top row of keys.
        #
        # The cap on the right is the SKIN'S, not the product's:
        # `card_faces.cap_for` asks how many characters this badge's face fits
        # across the panel, so a wide face gives eight and a narrow one gives
        # twelve.  Naming the face beside the field is what makes a short field
        # legible as a property of the ARTWORK rather than as the editor
        # arbitrarily refusing letters.
        if editor.limit < model.NAME_MAX:
            note = plan["badge"]["face"].upper()
            self._text(note, chrome.width - self.text_x - self._width(note),
                       y, self.grey)
        self._text(typed, self.text_x, y, self.white)
        # A BLOCK caret after the text rather than an underline under it: at one
        # logical pixel an underline is invisible at LORES, and the block also
        # shows that an EMPTY field is still taking input.
        screen.pen = self.accent
        screen.rectangle(self.text_x + self._width(typed), y, self.caret_w,
                         chrome.text_h)

        row, column, _goal = editor.caret()
        rows = editor.rows
        for index in range(len(self.cells)):
            line = self.cells[index]
            cells = rows[index]
            self.cell_h = self.row_heights[index]
            top = self.row_y[index]
            for position in range(len(line)):
                x, cell_w = line[position]
                self._cell(cells[position], x, top, cell_w,
                           index == row and position == column)
        # Descriptive hardware-button hints, never cells and never selectable.
        self._draw_button_hints()
