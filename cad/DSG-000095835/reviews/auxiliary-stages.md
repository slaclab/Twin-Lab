# Auxiliary stage review

Reviewed 2026-09-09 using the imported occurrence transforms, cached BREP shapes,
rendered solid geometry, and targeted BREP minimum-distance queries. Coordinates
below are in the STEP assembly frame and millimeters unless stated otherwise.

## Stage identities and motion

`A012` and `A018` are `LIB-000032451` with `REF-000222635` as the moving
Z carriage and `REF-000423701` as the fixed body/motor. The top carriage is the
**first** leaf in this library, unlike many fixed-first stage libraries. Its
geometry matches the Kohzu ZA05A wedge-lift family; exact library-to-vendor
variant identification remains provisional. The manufacturer specifies a
50 × 50 mm table and ±4 mm travel for
[ZA05A-W101](https://www.kohzuprecision.com/products/positioning-stages/item/za05a-w101/).
Use ±0.004 m as provisional local-simulation limits.

`A014` and `A020` are `LIB-000032478`, mapped to XA05A-R202 by the existing
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
| Lower | `P166`, top Z = −165.354 | `A012`, top Z = −109.354 | `A014`, top Z = −89.354 | `A010`: `P073`, `P074`, `P077`; blade holder `P497`, blades `P424/P425` |
| Upper | `P068`, top Z = −63.754 | `A018`, top Z = −7.754 | `A020`, top Z = 12.246 | `A016`: `P122`, `P123`; blade holder `P194`, blades `P422/P423` |

The exact matching horizontal mating planes establish the order **fixed mount
→ Z lift → X translation → payload**, independently for each chain. `P068`,
`P166`, the pedestal posts, and `P176` remain fixed to the assembly.

The slit blades are not inside `A009/A015`. The STEP places each blade holder
`DSG-000000720` (`P497` lower, `P194` upper) and its two 3.2 mm blade plates
`mo39143619/mo39143620` (`P424/P425` lower, `P422/P423` upper) directly under the
chamber assembly `A003`. Each holder sits on the tip of its blade rod (`P077`
spans X −144.8…19.0 at Z −26.7…−14.0; `P497` spans X 6.7…18.7 at Z −26.3…−14.4;
`P123` and `P194` match the same way at Z +14), and four 5-40 × 1.5 in screws
(`P450/P453/P495/P496` lower, `P491/P498/P499/P502` upper) pass through the
holder and both blades. Holder and blades therefore ride the X stage with the rod.
Earlier reviews left them on the fixed assembly, which reported every slit
motion as rod-to-holder contact.

The following lists exclude explicitly named screws. Any part subsequently
pruned by the assembly recipe should simply be removed from these lists.

| Body | Occurrences |
| --- | --- |
| Lower fixed | `P086 P087 P088 P094 P099 P100 P101` |
| Lower Z carriage, child of fixed | `P085 P091 P097 P103 P106 P107 P110` |
| Lower X carriage, child of lower Z | `P104 P105 P111 P073 P074 P077 P497 P424 P425` |
| Upper fixed | `P135 P136 P137 P143 P148 P149 P150` |
| Upper Z carriage, child of fixed | `P134 P140 P146 P152 P155 P156 P159` |
| Upper X carriage, child of upper Z | `P153 P154 P160 P122 P123 P194 P422 P423` |

The sensor bodies stay on the fixed side of their own stage. In particular,
minimum BREP distance is zero for `P094`–`P088` and `P107`–`P106`; the former is
2.506 mm from the moving bracket `P091`, and the latter 2.515 mm from moving
bracket `P105`. `P110` touches `P106` and is assigned to that fixed X-stage
support. `P091` touches the Z carriage `P085`. Thin pieces `P097/P111` (repeated
as `P146/P160`) follow the respective moving bracket and appear to be encoder
targets/shims. Exact sensor model names are not claimed.

The moving brackets `P091/P140` keep a constant 0.787 mm source-CAD gap to their
lift bodies `P086/P135` over the full ±4 mm travel, which the inflated hulls fill.
They are listed with the carriage as bearing parts so that running clearance is
not reported as contact. Likewise the X-stage sensor brackets `P106/P155` keep
0.498 mm to the X carriage `P104/P153` over ±7.5 mm and are listed with the fixed
X-stage body; the moving bracket `P105/P154` is still checked against them.
Downward lift travel ends at real stops, which stay reported. The Z carriage
`P085/P134` reaches the fixed bracket `P087/P136` after 1.725 mm, and `P094`
would reach the X-stage base `P103` after 1.83 mm (source CAD). The chamber port `P403` hulls fill the bores the blade
rods pass through; the CAD keeps at least 2.73 mm around each rod at every corner
of its y/x travel, so those two pairs are reviewed `ignored_pairs`.

`P100/P101` and their upper copies `P149/P150` are small pin-shaped
`LIB-000027156` hardware and may be pruned. The thin encoder targets may also be
pruned for a simpler display. Keep the substantial moving brackets and payload.

## Other manual adjustments and datum geometry

The previous STEP revision included a Kohzu RM07A-C1 manual rotary stage; the
2026-10-29 revision no longer contains it. Its published manual adjustment is
coarse 360° and fine ±3°; see the separately recorded source in
`stage-research.md`.

`A031` / `LIB-000013709` is a manual swivel stage, not an XY translation stage.
Rendered `P325` has curved guideways and a handwheel; `P327` is its matching
curved-underside top plate. `P326` is a separate 10 mm sphere with volume
523.5988 mm³. Its center lies on the stage normal, 86 mm above the base and
68 mm above the top mounting plane; it is a remote-center datum marker.

The 50 mm table, 18 mm height, 68 mm work distance, and handwheel strongly
match [Kohzu SH05B-RM](https://www.kohzuprecision.com/products/positioning-stages/item/sh05b-rm/),
whose manufacturer specifies manual ±10° adjustment. The user confirmed this
model on 2026-11-05. It is modelled as the manual joint `epix100_tilt_joint`
(±10°): `P325` rides the Kohzu table below, and `P327` carries the ePix100 arm.
Every guideway arc on both parts (radii 73.5–81.3 mm) shares one axis along
world X through (y 29.308, z −5.162) mm, and the datum sphere `P326` is centred
on that axis at x −159.657 mm, which is the joint pivot. `P326` itself stays
omitted as nonphysical. There is no controller mapping for this adjustment.

## ePix100 stack (`DSG-000042618`)

The upward-facing ePix100 module `mo39154223` rides this chain, base to payload.
The fixed column `P302`/`P328`/`P202` stands on breadboard `P193`, then:

1. `LIB-000000725` (`P197`), a lead-screw linear stage along world X. Its motor
   is at the outer end, and it is one fused solid. Cross-sections give a fixed
   channel with a central guide rail (local X −15…9, Y up to 1.0). The carriage
   plate, guide block, right-side flag skirt and hex drive nut sit at local Z
   59.0–133.1 mm and move. The screw (r 3.17 mm) stays fixed. The end-block faces
   at local Z −33.2 and +234.8 allow −92.2/+101.7 mm of carriage travel.
2. Adapter `P199`. Its M3 counterbores (32 × 40 mm) sit 61.19 mm along +Z from
   the matching tapped holes in the modelled carriage, so the payload is not on
   the carriage the fused part shows. The carriage region is offset by that much
   (`moving_offset_mm`).
3. `LIB-000005430` (`P313`), an old Kohzu 70 mm manual cross-roller X stage along
   world Y. It is also fused, as one part rather than a base and table assembly.
   The inverted-U table (top plate above local Z 12.5, skirts at |X| 26.8–35 down
   to Z 7.1) moves. The base, its rails (|X| 19–25.2, up to Z 12.0), micrometer
   and lock stay. Travel is ±6.5 mm, from the current Kohzu XM07A-S1 datasheet
   (70 × 70 mm, cross-roller, 13 mm micrometer).
4. The 10° wedge adapter `P196`, with `P329`, then the SH05B-RM swivel above.
5. Arm `P330`, end plate `P204` with `P201`, and the module parts
   `P205`/`P206`/`P209`/`P298`/`P299`/`P301`, front and rear covers `P266`/`P222`
   and cooling block `P249`/`P250`. The coolant fittings and tubes
   `P251`–`P258`/`P288`, transceiver `P240` and ribbon cable `P247` protrude from
   the rear face and are retained; everything the covers enclose is omitted.
