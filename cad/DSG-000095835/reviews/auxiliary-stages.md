# Auxiliary stage review

Reviewed 2026-09-09 using the imported occurrence transforms, cached BREP shapes,
rendered solid geometry, and targeted BREP minimum-distance queries. Coordinates
below are in the STEP assembly frame and millimeters unless stated otherwise.

## Stage identities and motion

`A024` and `A030` are `LIB-000032451` with `REF-000222635` as the moving
Z carriage and `REF-000423701` as the fixed body/motor. The top carriage is the
**first** leaf in this library, unlike many fixed-first stage libraries. Its
geometry matches the Kohzu ZA05A wedge-lift family; exact library-to-vendor
variant identification remains provisional. The manufacturer specifies a
50 × 50 mm table and ±4 mm travel for
[ZA05A-W101](https://www.kohzuprecision.com/products/positioning-stages/item/za05a-w101/).
Use ±0.004 m as provisional local-simulation limits.

`A026` and `A032` are `LIB-000032478`, mapped to XA05A-R202 by the existing
DSG-000040389 stage inventory and matching child reference names/geometry.
`REF-000423699` is the fixed motor/base and `REF-000226205` is the moving top.
The manufacturer specifies a 50 × 50 mm table, ±7.5 mm travel, and 5 mm/s maximum
speed for [XA05A-R202](https://www.kohzuprecision.com/products/positioning-stages/item/xa05a-r202/).
Use ±0.0075 m for this local simulation; the physical controller zero and limits
have not been established.

Both Z stages travel along local +Z, which is world +Z. Both X stages travel
along local +X, which is world +X. The sign establishes a convenient simulation
convention; it is not a motor/controller polarity claim.

## Physical chain and retained ownership

| Chain | Fixed mount | Z stage | X stage | Moving payload |
| --- | --- | --- | --- | --- |
| Lower | `P429`, top Z = −165.354 | `A024`, top Z = −109.354 | `A026`, top Z = −89.354 | `A022`: `P336`, `P337`, `P340` |
| Upper | `P331`, top Z = −63.754 | `A030`, top Z = −7.754 | `A032`, top Z = 12.246 | `A028`: `P385`, `P386` |

The exact matching horizontal mating planes establish the order **fixed mount
→ Z lift → X translation → payload**, independently for each chain. `P331`,
`P429`, the pedestal posts, and `P439` remain fixed to the assembly.

The following lists exclude explicitly named screws. Any part subsequently
pruned by the assembly recipe should simply be removed from these lists.

| Body | Occurrences |
| --- | --- |
| Lower fixed | `P349 P350 P351 P357 P362 P363 P364` |
| Lower Z carriage, child of fixed | `P348 P354 P360 P366 P369 P370 P373` |
| Lower X carriage, child of lower Z | `P367 P368 P374 P336 P337 P340` |
| Upper fixed | `P398 P399 P400 P406 P411 P412 P413` |
| Upper Z carriage, child of fixed | `P397 P403 P409 P415 P418 P419 P422` |
| Upper X carriage, child of upper Z | `P416 P417 P423 P385 P386` |

The sensor bodies stay on the fixed side of their own stage. In particular,
minimum BREP distance is zero for `P357`–`P351` and `P370`–`P369`; the former is
2.506 mm from the moving bracket `P354`, and the latter 2.515 mm from moving
bracket `P368`. `P373` touches `P369` and is assigned to that fixed X-stage
support. `P354` touches the Z carriage `P348`. Thin pieces `P360/P374` (repeated
as `P409/P423`) follow the respective moving bracket and appear to be encoder
targets/shims. Exact sensor model names are not claimed.

`P363/P364` and their upper copies `P412/P413` are small pin-shaped
`LIB-000027156` hardware and may be pruned. The thin encoder targets may also be
pruned for a simpler display. Keep the substantial moving brackets and payload.

## Other manual adjustments and datum geometry

`P636` explicitly names Kohzu RM07A-C1. It is a manual rotary stage; retaining
the complete leaf as fixed geometry preserves the imported setting. Its
published manual adjustment is coarse 360° and fine ±3°; see the separately
recorded source in `stage-research.md`.

`A043` / `LIB-000013709` is a manual swivel stage, not an XY translation stage.
Rendered `P588` has curved guideways and a handwheel; `P590` is its matching
curved-underside top plate. `P589` is a separate 10 mm sphere with volume
523.5988 mm³. Its center lies on the stage normal, 86 mm above the base and
68 mm above the top mounting plane; it is a remote-center datum marker.

The 50 mm table, 18 mm height, 68 mm work distance, and handwheel strongly
match [Kohzu SH05B-RM](https://www.kohzuprecision.com/products/positioning-stages/item/sh05b-rm/),
whose manufacturer specifies manual ±10° adjustment. This is a geometry-based
identification, not an established mapping from `LIB-000013709`. Keep `P588`
and `P590` fixed at the imported pose and prune `P589` as a nonphysical datum.
No automated joint or controller mapping is justified for this adjustment.
