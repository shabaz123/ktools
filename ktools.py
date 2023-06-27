# ktools: KiCad tools
# rev 1 - shabaz - first version

# usage:
# From KiCad PCB Editor, go to Tools->Scripting Console
# From the scripting console, select File->Open and select this file

import pcbnew

def welcome():
    print("Welcome to ktools v0.1")

# tLists all footprint references, and the component value and co-ordinates
# if format is "python" then a Python script is generated to move footprints to the current co-ordinates
def list_coords(format = ""):
    brd = pcbnew.GetBoard()
    fp_list = brd.GetFootprints()
    if format == "python":
        print("import pcbnew")
        print("brd = pcbnew.GetBoard()")
        print("def move_items():")
    for fp in fp_list:
        vect = fp.GetPosition()
        orient = fp.GetOrientation()
        if format == "":
            print(fp.GetReference(), fp.GetValue(), vect.x/1e6, vect.y/1e6, orient.AsDegrees())
        elif format == "python":
            print(f'    fx = brd.FindFootprintByReference("{fp.GetReference()}")')
            print("    if fx is not None:")
            print(f'        fx.SetPosition(pcbnew.VECTOR2I(pcbnew.wxPoint({vect.x}, {vect.y})))')
            print(f'        fx.SetOrientation(pcbnew.EDA_ANGLE({orient.AsDegrees()}, pcbnew.DEGREES_T))')
    if format == "python":
        print('    pcbnew.Refresh()')


if __name__ == '__main__':
    welcome()
