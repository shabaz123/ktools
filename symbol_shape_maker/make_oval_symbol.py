#!/usr/bin/env python3

# make_oval_symbol.py
# rev 1 - Sep 2024 - shabaz
#
# caculate XY coordinates of an oval shape (two semi-circles connected by two lines)
# and write to a file in the format of a symbol file for KiCad
# usage: python make_oval_symbol.py [width] [height] [split]
# the program uses a template file (symbol_template.txt)

import math
import os
import sys

template_filename = "symbol_template.txt"
width = 12.7
height = 6.35
degrees_per_step = 15
dest_file_prefix = "oval"

# get width and height as command line parameters
if len(sys.argv) > 2:
    width = float(sys.argv[1])
    height = float(sys.argv[2])
if width % 1.27 > 0.001 or height % 1.27 > 0.001:
    width_preferred = round(width / 1.27) * 1.27
    height_preferred = round(height / 1.27) * 1.27
    print(f"Multiples of 1.27 mm are preferred. Use {width_preferred} {height_preferred} (y/n)?")
    if input() == 'y':
        width = width_preferred
        height = height_preferred
do_split = False
if len(sys.argv) > 3:
    if sys.argv[3] == "split":
        dest_file_prefix = "oval_split"
        do_split = True
dest_filename = f"{dest_file_prefix}_{width}x{height}.kicad_sym"

# semicircle parameters
radius = height / 2
center_x = (width-height) / 2
center_y = 0

# right-side semi-circle:
points = []
for i in range(0, 180, degrees_per_step):
    x = center_x + radius * math.sin(math.radians(i))
    y = center_y + radius * math.cos(math.radians(i))
    points.append((x, y))
points.append((points[0][0], -points[0][1]))
# top line:
if do_split:
    points.append((0, -points[0][1]))
else:
    points.append((-points[0][0], -points[0][1]))
    # left-side semi-circle:
    for i in range(180, 360, degrees_per_step):
        x = radius * math.sin(math.radians(i)) - center_x
        y = center_y + radius * math.cos(math.radians(i))
        points.append((x, y))
    points.append((-points[0][0], points[0][1]))
# bottom line:
if do_split:
    # insert a point at the beginning of the list
    points.insert(0, (0, points[0][1]))
else:
    points.append((points[0][0], points[0][1]))

# delete any duplicate points
i = 0
while i < len(points) - 1:
    if points[i] == points[i + 1]:
        del points[i]
    else:
        i += 1

# read template file contents into a list:
with open(template_filename, 'r') as file:
    lines = file.readlines()

# copy to destination file until <DATA> is found:
dst_file = open(dest_filename, 'w')
key_found = False
linenum = 0
for line in lines:
    if "<DATA>" in line:
        key_found = True
        break
    dst_file.write(line)
    linenum += 1
if not key_found:
    print("Error: <DATA> not found in template file.")
    sys.exit(1)

# count indent depth
num_tabs = lines[linenum].count('\t')
tabs = ""
for i in range (0, num_tabs):
    tabs += "\t"

# write polyline
dst_file.write(tabs + "(polyline\n")

# write and close pts
dst_file.write(tabs + "\t(pts\n")

for i in range(0, len(points), 6):
    line = tabs + "\t\t"
    for j in range(i, min(i + 6, len(points))):
        line += f"(xy {points[j][0]:.2f} {points[j][1]:.2f}) "
    dst_file.write(line + "\n")
dst_file.write(tabs + "\t)\n")

# write and close stroke
dst_file.write(tabs + "\t(stroke\n")
dst_file.write(tabs + "\t\t(width 0.254)\n")
dst_file.write(tabs + "\t\t(type default)\n")
dst_file.write(tabs + "\t)\n")

# write and close fill
dst_file.write(tabs + "\t(fill\n")
dst_file.write(tabs + "\t\t(type background)\n")
dst_file.write(tabs + "\t)\n")

# close polyline
dst_file.write(tabs + ")\n")

# write the rest of the template file
for line in lines[linenum + 1:]:
    dst_file.write(line)

# close the destination file
dst_file.close()

print(f"Done, {dest_filename} written.")
print(f"Now use Symbol Editor File->Import->Symbol.")
