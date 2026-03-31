# EnviroSat — structure/

This folder contains the physical enclosure files for EnviroSat.

## Files

### envirosat_enclosure.stl
3D-printable enclosure for all three boards.

Recommended print settings:
- Material:     PETG (heat resistant, slightly flexible)
- Layer height: 0.2 mm
- Infill:       25% (gyroid pattern recommended)
- Supports:     Required for the antenna port and camera cutouts
- Estimated print time: 4–6 hours on a standard FDM printer

The STL file is generated from the parametric design source (OpenSCAD).
Print two halves: a base tray (holds all three boards on standoffs) and
a lid with cutouts for:
  - SMA antenna connector (HaLow)
  - USB-A port (HaLow module)
  - Camera lens opening (×2, one per camera)
  - Ventilation slots (top face)
  - LED indicator window (front face)
  - Power switch hole (side face)

### enclosure_assembly.pdf
Step-by-step illustrated assembly guide for placing the three boards
inside the printed enclosure, routing cables, and closing the lid.

Covers:
  1. Installing M2.5 standoffs in the base tray
  2. Mounting Board 1 (Pi + hats)
  3. Mounting Board 2 (UPS HAT batteries)
  4. Routing antenna cable through the SMA port
  5. Mounting Board 3 (comms + motor shield)
  6. Cable management and tie-down points
  7. Closing the lid and securing with M3 screws
  8. Pre-deployment checklist

## Notes
- STL and PDF files are binary/designed assets not included in this
  text repository. Download them from the GitHub releases page or
  the project website.
- If you prefer an open-frame build (no enclosure), Sections 8.2–8.4
  of the build guide cover alternative mounting approaches.
