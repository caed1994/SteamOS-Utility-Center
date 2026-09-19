# SPDX-FileCopyrightText: 2026 caed1994
# SPDX-License-Identifier: GPL-3.0-or-later

"""Where the toolbox is, and the measurements every page of the window uses.

The window is one class of five thousand lines, and the work to cut it into
one module per page starts here. This is what those modules stand on: a page
needs the gaps it spaces its rows with, and where the toolbox it calls lives.
Neither of those belongs to any one page.

A page module cannot read these from the window itself. The window imports
the page and the page would import the window back, and Python refuses that.
So they are here, where both read them and neither owns them.

The values are unchanged. They were in gui/steamos-utility-center-panel, with
the comments they still carry.
"""

from __future__ import annotations

import os

import material

# Where this project is, from the file this module is in.
#
# The panel, the installer behind its repair button, the appliers and the
# firmware project are all under it. The installer puts a copy of the whole
# toolbox in /var/lib/steamos-utility-center/source and points the menu entry
# there, so on a machine this reads that copy and not a clone.
HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE_DIR = os.path.dirname(HERE)

# The maximum width of the content of a page, for each monitor. These pages
# are a column of labels and controls. Above this width the column is no
# longer a column: the label is at one end of the movement of the eye, and its
# control is at the other end. On a 2560 monitor the margin takes the extra
# width.
CONTENT_MAX = 1040

# What a card takes from the width of the page it stands on: the border of the
# notebook, the margin at each side of the card, and the padding inside it.
#
# This uses material.SPACE and not GROUP_GAP. GROUP_GAP is six of these, and
# this file declares it below. A constant cannot use a later constant.
#
# One value, because two places subtract it. CARD_WRAP below is the width a
# paragraph has before the window is measured, and Panel._rewrap is the width
# it has after.
#
# Those two were not equal. _rewrap subtracted three side margins, which is
# 48, and this line subtracted 96. A paragraph on a page thus had 48 pixels
# more than its card. A sentence whose last word crossed that line was cut at
# the edge of the card, and a sentence one word shorter was not. The HDMI CEC
# page stood one pixel from it.
CARD_INSET = 24 * material.SPACE

# The maximum width of a paragraph in a card. The card has the width
# CONTENT_MAX at its widest, and it has padding on both sides. A paragraph
# that wraps at CONTENT_MAX puts its last words past the edge of the card.
CARD_WRAP = CONTENT_MAX - CARD_INSET

# The 4dp grid Material spaces everything on, in the amounts this window needs.
# The gap between groups is what replaces the boxes that used to be drawn round
# them, so it is deliberately larger than any gap inside one.
SIDE_MARGIN = 4 * material.SPACE

# How wide the switch column on the CEC page is, so a feature's sentence lines
# up under its own label rather than under the switch.
CEC_INDENT = 9 * material.SPACE

# The same for a status block: its sentence sits under the part's name rather
# than under the light beside it.
PART_INDENT = 6 * material.SPACE
# The room a compact status row keeps for its Details button, so a long
# sentence wraps before it and does not run under it.
FOLD_ROOM = 32 * material.SPACE
GROUP_GAP = 6 * material.SPACE
ROW_GAP = 2 * material.SPACE
INDENT_STEP = 5 * material.SPACE

# The space that one settings row keeps above and below its control. The
# second value is the extra space of a row that starts a block. That row is
# the switch above an indented pair. Each control has the same height, so that
# extra space is the one sign of the end of one block and the start of the
# next block.
#
# The value is six on each side, so there are twelve pixels between two
# controls. That is the spacing of Material for a list of controls. With four
# pixels, two filled shapes of forty pixels looked like one shape. A switch
# above a drop-down had that fault.
ROW_PAD = 6
BLOCK_GAP = 4 * material.SPACE

# The width of the one drop-down whose entries are paths into /sys.
#
# Every other settings menu is MENU_WIDTH, so a column of them has a straight
# edge. This one is wider because a cut path removes the information that a
# person needs: the name of the sensor they picked.
#
# Here and not in the panel, because the System page reads it as well. See
# the note at the top of this file.
SENSOR_WIDTH = 30
