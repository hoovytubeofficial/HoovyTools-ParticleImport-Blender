# =============================================================================
#  Calculate Particle Size (V1)
#  The Text Editor version of  Source Particle Import > Tools > 5.1 Calculate
#  Particle Size (Source Particle Import 3.0.0).
# =============================================================================
#
#  WHAT IT DOES: reads a .pcf - nothing is imported - and estimates the box
#  each effect can fill, in Hammer units and metres: where its particles
#  spawn, how far the fastest one travels in the longest lifetime (slowed by
#  drag the way Source does it), how far gravity pulls it, the jitter of
#  Random Force, plus the largest card or trail. Children born on their
#  parent's particles start from the parent's whole cloud. An upper bound:
#  turbulence and attraction only keep particles closer.
#
#  HOW: set the values below, press Run Script (Alt+P). The sizes print to the
#  console (Window > Toggle System Console), every line starting with
#  [Source Particle Import], and the Tools tab shows the last answer.
#
#  Needs the Source Particle Import add-on (3.0.0 or newer) installed.
#
#  THIS FEATURE WAS ADDED IN VERSION 3.0.0 AND IS IN EXPERIMENTAL STAGE.
# =============================================================================

PCF_FILE = r""              # the .pcf; "" = the one chosen on the Import tab
SYSTEM = ""                 # one system's name; "" = every root system in the file
INCLUDE_CHILDREN = True     # count the child systems too

# -----------------------------------------------------------------------------

import addon_utils
import bpy

NAMES = ("HoovyTools-ParticleImport-Blender-Master", "HoovyTools-ParticleImport-Blender-master",
         "HoovyTools-ParticleImport-Blender-main")


def main():
    if not hasattr(bpy.ops.htp, "calculate_particle_size"):
        #  enable it ONLY when it is off - enabling twice re-registers it under this running script
        for name in NAMES:
            loaded, enabled = addon_utils.check(name)
            if loaded is not None and not enabled:
                addon_utils.enable(name, default_set=True)
                break
    if not hasattr(bpy.ops.htp, "calculate_particle_size"):
        raise RuntimeError("Source Particle Import is not installed - install it, then run this again")
    kw = {"include_children": INCLUDE_CHILDREN, "whole_file": not SYSTEM}
    if PCF_FILE:
        kw["pcf_path"] = PCF_FILE
        kw["system"] = SYSTEM
    print(bpy.ops.htp.calculate_particle_size(**kw))


main()
