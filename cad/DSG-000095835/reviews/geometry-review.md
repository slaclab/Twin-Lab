# Geometry and ownership review

The original STEP is preserved. Source reference assignments come from its
generated `manifest.json`; every leaf is explicitly retained or omitted.

The lower upright Parker is `A068` (`P716` fixed, `P717` moving). Its carriage
carries adapter `P733`, bracket `P698`, and the horizontal Parker `A065`.
The latter has `P684` fixed and `P685` moving. Its moving bracket is
`P730/P731/P732`, which carries the Huber fixed body and motor. Both Parker
travel axes are local +Z in this particular vendor CAD, established by the
long slide-base direction. Both imported carriages are provisionally treated
as centered in their 100 mm travel.

The Huber rotates around local +Y. Its top carries `P968`, the three long
posts `P973/P974/P979`, and front plate `P790`. The four crystal stacks
branch from that plate. Each chain is XA07A translation → `LIB-000032444`
rotation → SA04B tilt → crystal adapter and payload. The touching mounting
planes, from the front plate toward the crystals, establish this order. Since
the 2026-11-04 revision the rotation stage `LIB-000032444` (which replaced the
RA04A-W) has no solids in the STEP. Its axis is carried with the adapter
`mo39185433` above it, unchanged from the RA04A review.

The vendor STEP fuses some moving interfaces into single solids. These are
partitioned using masks at the visible mechanical seams:

| Stage | Moving region | Local motion |
| --- | --- | --- |
| XA07A-L201 | 70 mm upper table, carriage blocks and nut; fixed rail/screw envelopes excluded | +X translation |
| RA04A-W (no longer in the design; template kept) | Exposed 40 mm rotor above Z=24.25 mm; hidden bearing detail left fixed | +Z rotation through origin |
| SA04B-RM01 | Curved saddle, using stepped cylindrical cuts between mating bearing surfaces | +Y rotation through (0, 0, 74) mm |
| Huber 410 | 138 mm rotor above Y=49.7 mm | +Y rotation through origin |
| IMS300CC | Carriage top plate. Only the 2026-11-04 14:01 STEP needed the lower slide's plate offset (80.1151 mm along local −Z) to sit under its payload | +Z translation |

The fused ePix100 stages `LIB-000000725` and `LIB-000005430` had masks too. They
left the design in the 2026-11-12 export, replaced by multi-part models, and their
templates were removed.

The ePix10k's ZA16A needs no mask, because its moving parts are already separate
solids, selected by index in the recipe:

- The ePix10k's Kohzu ZA16A-W2C01 (`P1138`) is Kohzu's own STEP: same bounds and
  nine solid volumes as the vendor download. Solid 1, the 160 mm table, has the
  downward-facing 14.04° faces of the 1/4 wedge. Solid 6 is the wedge (upward
  14.04° faces) and solid 7 a rail fixed to it (touching it, 0.5 mm below the
  table); solid 8 is the base and motor, and solids 2–5 the feet. The table rises
  1 mm for every 4 mm the wedge slides towards local −X (world +Y), so the wedge
  joint follows the table joint at a ratio of 4. That keeps the drawn 0.5 mm
  table-to-wedge and wedge-to-base clearances at every height. At +8 mm the wedge
  tip, at local X −77, reaches −109, which is the "(29)" overhang past the −80
  front face in the vendor drawing. The table face is at local Z 80.0, the
  "80 ± 8" of the vendor drawing, so the CAD pose is mid-travel.

The ePix100's M-EL80 lab jack is a 14-part model since the 2026-11-12 export.
Its scissor arms and sliding blocks follow the top plate by the exact scissor
relation; see `auxiliary-stages.md`.

The Kohzu manufacturer drawing puts the SA04B-RM01 rotation center 57 mm
above its 17 mm-high moving table. The source CAD contains a spherical datum
at local (0, 0, 74) mm, independently confirming the center. That sphere is
omitted. The swivel's motor/coupling solids stay on its fixed body. Rotary
stage cable detail and small loose sensor/fastener solids are omitted.

These are geometric approximations of fused parts, not manufacturer-supplied
separate bodies. The imported swivel solid contains invalid/inverted fragments
around screw holes. The builder keeps only positive split solids of at least
100 mm³, removing those fragments and disconnected fastening detail before
meshing. The principal stage bodies and moving faces remain intact.

Kinematic distances use metres and radians. Geometry masks alone use the
original CAD millimetres. Occurrence transforms place each selected region
back into the original assembly pose before meshing; a shared parent then
moves all descendants together.

The outer structural cage `A042` is retained as 52 separate non-fastener
occurrences on `assembly_base`. Its open interior is preserved by decomposing
each member separately. It stays fixed when either Parker slide or the inner
analyzer frame moves. The two slit towers described in auxiliary-stages.md
are driven again (bottom and top slit y/x), alongside the liquid-jet and
ePix10k stages.
