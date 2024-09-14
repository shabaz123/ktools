#!/usr/bin/env python3

# sim_select.py
# rev 1 - Sep 2024 - shabaz
#
# This code is used to set/reset the exclude_from_sim attribute in KiCad schematic files.
# usage: python3 sim_select.py [schematic_filename]
# If the schematic_filename is not provided, the user will be prompted with a selection.

import os
import sys
import shutil

sim_filename = ""
sch_files = []  # list of schematic files in the current directory

def get_sch_filenames():
    global sch_files
    sch_files = []
    for file in os.listdir():
        if file.endswith(".kicad_sch"):
            sch_files.append(file)
    return sch_files

sch_files = get_sch_filenames()
if len(sch_files) == 0:
    print("Error: no schematic files found in the current directory, aborting.")
    sys.exit(1)
sch_files.sort()

# determine the name of the file to be simulated
if len(sys.argv) > 1:
    sim_filename = sys.argv[1]
    if sim_filename not in sch_files:
        print(f"Error: {sim_filename} not found in the current directory, aborting.")
        sys.exit(1)
else:
    print("Select a schematic to simulate:")
    for i, file in enumerate(sch_files):
        print(f"{i+1}: {file}")
    selection = int(input(f"Enter the number of the schematic (1-{len(sch_files)}): "))
    if selection < 1 or selection > len(sch_files):
        print("Error: invalid selection, aborting.")
        sys.exit(1)
    sim_filename = sch_files[selection-1]

print(f"Selected file to simulate: {sim_filename}")
confirm = input("Continue? (y/n): ")
if confirm.lower() != 'y':
    print("Aborted, exiting.")
    sys.exit(1)


# backup files
if not os.path.exists("sim_backup"):
    os.mkdir("sim_backup")
backup_dirs = []
backup_dirs_suffix = []
for dir in os.listdir("sim_backup"):
    if os.path.isdir(f"sim_backup/{dir}"):
        backup_dirs.append(dir)
for dir in backup_dirs:
    suffix = dir.split('_')[2]
    backup_dirs_suffix.append(int(suffix))
backup_dirs_suffix.sort()
# keep only the 10 most recent backups
if len(backup_dirs) > 9:
    oldest_backup = f"sim_backup_{backup_dirs_suffix[0]}"
    print(f"Deleting oldest backup folder: {oldest_backup}")
    if os.name == 'nt':
        shutil.rmtree(f"sim_backup/{oldest_backup}")
    else:
        os.system(f"rm -r sim_backup/{oldest_backup}")
# create the new backup directory
if len(backup_dirs_suffix) == 0:
    last_backup_suffix = 0
else:
    last_backup_suffix = backup_dirs_suffix[-1]
backup_dir_filename = f"sim_backup_{last_backup_suffix+1}"
os.mkdir(f"sim_backup/{backup_dir_filename}")
# copy all schematic files to the new backup directory
for file in sch_files:
    if os.name == 'nt':
        cmd = f"copy {file} sim_backup/{backup_dir_filename}/{file}"
        shutil.copy(file, f"sim_backup/{backup_dir_filename}/{file}")
    else:
        os.system(f"cp {file} sim_backup/{backup_dir_filename}/{file}")
print(f"Backup created in folder: sim_backup/{backup_dir_filename}")

# update the simulation attributes
num_updates = 0
for file in sch_files:
    with open(file, 'r') as f:
        lines = f.readlines()
    with open(file, 'w') as f:
        for line in lines:
            if "(exclude_from_sim" in line:
                num_updates += 1
            if file == sim_filename:
                f.write(line.replace("(exclude_from_sim yes)", "(exclude_from_sim no)"))
            else:
                f.write(line.replace("(exclude_from_sim no)", "(exclude_from_sim yes)"))
print(f"Simulation attributes updated: {num_updates}")
print("Finished, exiting.")
sys.exit(0)
