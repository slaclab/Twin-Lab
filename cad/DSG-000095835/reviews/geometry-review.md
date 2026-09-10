# Geometry and ownership review

The original STEP is preserved. Source reference assignments come from its
generated `manifest.json`; every leaf is explicitly retained or omitted.

The lower upright Parker is `A077` (`P938` fixed, `P939` moving). Its carriage
carries adapter `P955`, bracket `P920`, and the horizontal Parker `A074`.
The latter has `P906` fixed and `P907` moving. Its moving bracket is
`P952/P953/P954`, which carries the Huber fixed body and motor. Both Parker
travel axes are local +Z in this particular vendor CAD, established by the
long slide-base direction. Both imported carriages are provisionally treated
as centered in their 100 mm travel.

The Huber rotates around local +Y. Its top carries `P1180`, the three long
posts `P1185/P1186/P1191`, and front plate `P1045`. The three crystal stacks
branch from that plate. Each chain is XA07A translation → RA04A rotation →
SA04B tilt → crystal adapter and payload. The touching mounting planes, from
the front plate toward the crystals, establish this order.

The vendor STEP fuses some moving interfaces into single solids. These are
partitioned using masks at the visible mechanical seams:

| Stage | Moving region | Local motion |
| --- | --- | --- |
| XA07A-L201 | 70 mm upper table, carriage blocks and nut; fixed rail/screw envelopes excluded | +X translation |
| RA04A-W | Exposed 40 mm rotor above Z=24.25 mm; hidden bearing detail left fixed | +Z rotation through origin |
| SA04B-RM01 | Curved saddle, using stepped cylindrical cuts between mating bearing surfaces | +Y rotation through (0, 0, 74) mm |
| Huber 410 | 138 mm rotor above Y=49.7 mm | +Y rotation through origin |

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

The outer structural cage `A047` is retained as 68 separate non-fastener
occurrences on `assembly_base`. Its open interior is preserved by decomposing
each member separately. It stays fixed when either Parker slide or the inner
analyzer frame moves. The former auxiliary/LJ carriages are now fixed CAD
obstacles; their motor controls are disabled.
