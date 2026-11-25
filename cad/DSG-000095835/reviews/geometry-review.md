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

The fused ePix100 stages `LIB-000000725` and `LIB-000005430` had masks too. They
left the design in the 2026-11-12 export, replaced by multi-part models, and their
templates were removed. The fused ePix10k IMS300CC slides and Kohzu ZA16A-W2C01
followed in the 2026-11-21 export, and the IMS300CC template went with them.

The ePix10k stages need no masks, because their moving parts are separate parts:

- Each Newport IMS300CC (`LIB-000033136`) is a base and a 179 mm carriage. The
  base's carriage channel is open from local Z 0 to 513.5 mm and the library
  places the carriage at 167 mm, mid-channel, taken as mid-travel. The upper (x)
  carriage `P2151` is drawn there; the lower (z) carriage `P2149` is drawn
  134.378 mm towards world +Y.
- The Kohzu ZA16A-W2C01 (`LIB-000033137`) is a base `P2144` with pin `P2143`, a
  wedge `P2146` with retainer `P2145`, and a 160 mm table `P2147`. The table's
  downward and the wedge's upward incline faces have normal (0, 0.2425, 0.9701)
  in world, a 1/4 slope: the table rises 1 mm for every 4 mm the wedge slides
  along world +Y, so the wedge joint follows the table joint at a ratio of 4.
  The faces stay in contact, without overlap, at every height. The table face is
  80.01 mm above the base's mounting face, the "80 ± 8" of the vendor drawing,
  so the CAD pose is mid-travel.

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
