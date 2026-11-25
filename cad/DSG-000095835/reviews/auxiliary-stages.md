# Auxiliary stage review

Reviewed 2026-09-09 using the imported occurrence transforms, cached BREP shapes,
rendered solid geometry, and targeted BREP minimum-distance queries. Coordinates
below are in the STEP assembly frame and millimeters unless stated otherwise.

## Stage identities and motion

`A014` and `A020` are `LIB-000032451` with `REF-000222635` as the moving
Z carriage and `REF-000423701` as the fixed body/motor. The top carriage is the
**first** leaf in this library, unlike many fixed-first stage libraries. Its
geometry matches the Kohzu ZA05A wedge-lift family; exact library-to-vendor
variant identification remains provisional. The manufacturer specifies a
50 × 50 mm table and ±4 mm travel for
[ZA05A-W101](https://www.kohzuprecision.com/products/positioning-stages/item/za05a-w101/).
Use ±0.004 m as provisional local-simulation limits.

`A016` and `A022` are `LIB-000032478`, mapped to XA05A-R202 by the existing
DSG-000040389 stage inventory and matching child reference names/geometry.
`REF-000423699` is the fixed motor/base and `REF-000226205` is the moving top.
The manufacturer specifies a 50 × 50 mm table, ±7.5 mm travel, and 5 mm/s maximum
speed for [XA05A-R202](https://www.kohzuprecision.com/products/positioning-stages/item/xa05a-r202/).
Use ±0.0075 m for this local simulation; the physical controller zero and limits
have not been established.

Both Z stages travel along local +Z, which is world +Z. Both X stages travel
along local +X, which is world +X. These two towers are the bottom and top
slits; their joints are named in beamline axes (y = world +Z, x = world −X), so a
positive slit x moves along world −X. This is a simulation convention, not a
motor/controller polarity claim.

## Physical chain and retained ownership

| Chain | Fixed mount | Z stage | X stage | Moving payload |
| --- | --- | --- | --- | --- |
| Lower | `P192`, top Z = −165.354 | `A014`, top Z = −109.354 | `A016`, top Z = −89.354 | `A012`: `P099`, `P100`, `P103`; blade holder `P537`, blades `P461/P462` |
| Upper | `P094`, top Z = −63.754 | `A020`, top Z = −7.754 | `A022`, top Z = 12.246 | `A018`: `P148`, `P149`; blade holder `P220`, blades `P459/P460` |

The exact matching horizontal mating planes establish the order **fixed mount
→ Z lift → X translation → payload**, independently for each chain. `P094`,
`P192`, the pedestal posts, and `P202` remain fixed to the assembly.

The slit blades are not inside `A011/A017`. The STEP places each blade holder
`DSG-000000720` (`P537` lower, `P220` upper) and its two 3.2 mm blade plates
`mo39143619/mo39143620` (`P461/P462` lower, `P459/P460` upper) directly under the
chamber assembly `A003`. Each holder sits on the tip of its blade rod (`P103`
spans X −144.8…19.0 at Z −26.7…−14.0; `P537` spans X 6.7…18.7 at Z −26.3…−14.4;
`P149` and `P220` match the same way at Z +14), and four 5-40 × 1.5 in screws
(`P487/P491/P535/P536` lower, `P531/P538/P539/P542` upper) pass through the
holder and both blades. Holder and blades therefore ride the X stage with the rod.
Earlier reviews left them on the fixed assembly, which reported every slit
motion as rod-to-holder contact.

The following lists exclude explicitly named screws. Any part subsequently
pruned by the assembly recipe should simply be removed from these lists.

| Body | Occurrences |
| --- | --- |
| Lower fixed | `P112 P113 P114 P120 P125 P126 P127` |
| Lower Z carriage, child of fixed | `P111 P117 P123 P129 P132 P133 P136` |
| Lower X carriage, child of lower Z | `P130 P131 P137 P099 P100 P103 P537 P461 P462` |
| Upper fixed | `P161 P162 P163 P169 P174 P175 P176` |
| Upper Z carriage, child of fixed | `P160 P166 P172 P178 P181 P182 P185` |
| Upper X carriage, child of upper Z | `P179 P180 P186 P148 P149 P220 P459 P460` |

The sensor bodies stay on the fixed side of their own stage. In particular,
minimum BREP distance is zero for `P120`–`P114` and `P133`–`P132`; the former is
2.506 mm from the moving bracket `P117`, and the latter 2.515 mm from moving
bracket `P131`. `P136` touches `P132` and is assigned to that fixed X-stage
support. `P117` touches the Z carriage `P111`. Thin pieces `P123/P137` (repeated
as `P172/P186`) follow the respective moving bracket and appear to be encoder
targets/shims. Exact sensor model names are not claimed.

The moving brackets `P117/P166` keep a constant 0.787 mm source-CAD gap to their
lift bodies `P112/P161` over the full ±4 mm travel, which the inflated hulls fill.
They are listed with the carriage as bearing parts so that running clearance is
not reported as contact. Likewise the X-stage sensor brackets `P132/P181` keep
0.498 mm to the X carriage `P130/P179` over ±7.5 mm and are listed with the fixed
X-stage body; the moving bracket `P131/P180` is still checked against them.
Downward lift travel ends at real stops, which stay reported. The Z carriage
`P111/P160` reaches the fixed bracket `P113/P162` after 1.725 mm, and `P120`
would reach the X-stage base `P129` after 1.83 mm (source CAD). The chamber port `P439` hulls fill the bores the blade
rods pass through; the CAD keeps at least 2.73 mm around each rod at every corner
of its y/x travel, so those two pairs are reviewed `ignored_pairs`.

`P126/P127` and their upper copies `P175/P176` are small pin-shaped
`LIB-000027156` hardware and may be pruned. The thin encoder targets may also be
pruned for a simpler display. Keep the substantial moving brackets and payload.

## Other manual adjustments and datum geometry

The previous STEP revision included a Kohzu RM07A-C1 manual rotary stage; the
2026-10-29 revision no longer contains it. Its published manual adjustment is
coarse 360° and fine ±3°; see the separately recorded source in
`stage-research.md`.

`A024` / `LIB-000013709` is a manual swivel stage, not an XY translation stage.
Rendered `P245` has curved guideways and a handwheel; `P247` is its matching
curved-underside top plate. `P246` is a separate 10 mm sphere with volume
523.5988 mm³. Its center lies on the stage normal, 86 mm above the base and
68 mm above the top mounting plane; it is a remote-center datum marker.

The 50 mm table, 18 mm height, 68 mm work distance, and handwheel strongly
match [Kohzu SH05B-RM](https://www.kohzuprecision.com/products/positioning-stages/item/sh05b-rm/),
whose manufacturer specifies manual ±10° adjustment. The user confirmed this
model on 2026-11-05. It is modelled as the manual joint `epix100_tilt_joint`
(±10°): `P245` rides the Kohzu table below, and `P247` carries the ePix100 arm.
Every guideway arc on both parts (radii 73.5–81.3 mm) shares one axis along
world X through (y 29.308, z −5.162) mm, and the datum sphere `P246` is centred
on that axis at x −159.657 mm, which is the joint pivot. `P246` itself stays
omitted as nonphysical. There is no controller mapping for this adjustment.

## ePix100 stack (`DSG-000042618`)

The upward-facing ePix100 module `mo39154223` rides this chain, base to payload.
Fixed block `P229` stands on breadboard `P219`, then:

Since the 2026-11-12 export every stage here is a multi-part library model, so no
split masks are needed.

1. A manual Newport M-EL80 lab jack `LIB-000033108` (`A033`), confirmed by the
   user on 2026-11-11. The 2026-11-21 export draws it 83.000 mm high, mid-stroke,
   turned 180° about world Z from the 2026-11-12 export. It is a single scissor.
   - Base plate `P324` (fixed) and top plate `P323` carry the fixed pivots at
     x −129.231 mm, z −217.074 (bottom) and −160.174 (top), with pins `P332` and
     `P331`.
   - Arm A `P325` runs from the bottom pivot to top block `P328`, which slides in
     the top plate's channel. Arm B `P326` runs from the top pivot to bottom block
     `P329`. The blocks' pins at x −215.784 carry bushings `P333`–`P336`.
   - The arms are 103.581 mm between pivots and cross at their midpoints on
     centre pin `P330`.
   - Knob and screw `P327` run along world X through the top plate into `P328`,
     which is the nut.
   - `epix100_y_joint` lifts the top plate. Four follower joints set arm A and arm
     B (rotation about their pivots) and the two blocks (sliding along world X)
     from it by the scissor relation. Over the stroke, every pin stays seated, in
     contact with zero overlap.
   - The user asked for Newport's full 53–113 mm, so the joint runs −30.000 to
     +30.000 mm. The library CAD is drawn tighter than the real jack:
     - At 112.2 mm the arms' sliding ends cut 1.5 mm (36.5 mm³) into the plates'
       channels.
     - Below 72.8 mm arm B sweeps into the top plate's underside beside its pivot.
     - At 60.0 mm the top block meets its channel end.

     The jack's 14 parts are therefore an `ignored_groups` entry. They are not
     checked against each other, but they are still checked against everything
     else.
2. Adapter `P226`, then a Micronix VT-50L-13316 stepper stage `LIB-000033066`
   (base `P248`, carriage `P249`) along world X. -13316 is the 198 mm,
   digital-encoder, high-vacuum version.
   - The carriage can run 175.5 mm towards the motor, where its nut housing meets
     the motor mount, and 28.0 mm to the far end block (inner face at
     x −91.6 mm), 203.5 mm in all.
   - With the 198 mm limit-switch travel centred in that, the carriage is drawn
     73.8 mm from mid-travel, and `epix100_x_joint` (beamline x, world −X) runs
     −25.22/+172.78 mm.
3. Adapter `P223`, then the manual stage `LIB-000033109`: base `P365`, table `P366`
   and micrometer `P367` along world +Y. It replaces the earlier fused Kohzu
   model. The table touches the micrometer tip and slides only along world Y, but
   the CAD has no end stops, so it keeps that model's ±6.5 mm (Kohzu XM07A-S1).
4. The 10° wedge adapter `P222`, then the SH05B-RM swivel above.
5. Arm `P250`, end plate `P228` with `P225`, and the module parts
   `P251`/`P252`/`P255`/`P344`/`P345`/`P347`, front and rear covers `P312`/`P268`
   and cooling block `P295`/`P296`. The coolant fittings and tubes
   `P297`–`P304`/`P334`, transceiver `P286` and ribbon cable `P293` protrude from
   the rear face and are retained; everything the covers enclose is omitted.
