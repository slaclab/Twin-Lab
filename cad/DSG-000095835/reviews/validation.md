# STEP Revision of 2026-11-21 (SHA-256 `ac9d89fe…`)

The review was migrated from the `2f9a4891…` STEP. References below use the new
manifest; earlier entries use the references of their own revision.

- Mapping: 1,946 occurrences map parent by parent (CAD name without `_oa_`,
  placement within the parent). Duplicates are paired against the parent's
  dominant shift, so identical parts that moved together keep their partners.
  47 leaves left the design and 354 are new. The recipe text was remapped in one
  pass, keeping its comments; split-template names were not remapped. Every joint
  frame was carried with its stage part's world placement change.
- What moved, in world coordinates:
  - Everything outside chamber assembly `DSG-000102548` moved +48.766 mm in z
    and the spectrometer +0.257 mm in x, back up most of the 11-12 drop.
  - The ePix10k payload moved (+0.01, +45.26, +61.67) mm. Home is now clear:
    the 11-12 interference with chamber part `REF-000062451` is gone, and the
    regressions no longer allow it.
  - The ePix100 group moved −29.211 mm in z. Its M-EL80 lab jack is drawn
    83.000 mm high and turned 180° about world Z: fixed pivots now at
    x −129.231, sliding pins at x −215.784. The four scissor followers were
    re-derived (rise 56.900 mm, 33.32°), their axes turned with the jack, and
    ePix100 y runs ±30.000 mm for Newport's 53–113 mm. The top plate `P323`,
    arms and blocks match those pivots to 1e-6 mm.
- Restructured:
  - ePix10k stages are multi-part library models: two IMS300CC `LIB-000033136`
    (base and carriage) and the ZA16A-W2C01 `LIB-000033137` (base `P2144` with
    pin `P2143`, wedge `P2146` with retainer `P2145`, table `P2147`). The
    IMS300CC split template was removed.
    - Each IMS300CC channel is open from 0 to 513.5 mm and the library carriage
      sits at 167 mm, mid-channel. The upper carriage is drawn there (x ±150 mm);
      the lower is 134.378 mm towards world +Y (z −284.378/+15.622 mm).
    - The ZA16A incline faces have normal (0, 0.2425, 0.9701), a 1/4 slope, so
      the wedge follower keeps its ratio of 4. Table and wedge stay in contact at
      every height (Boolean overlap ≤ 0.015 mm³); the table face is 80.01 mm
      above the mounting face. Frame `P2054` clears the wedge by 9.297 mm at home
      and 1.297 mm at −8 mm. The table/wedge, table/retainer and frame/wedge
      pairs are `ignored_pairs`.
    - Plates `DSG-000007302` now hang under fixed base plate `P2124` and moved to
      `assembly_base`, with the lower IMS300CC base `P2148` on the risers.
  - Jet holder `DSG-000108486` (`P520`, on jet adapter `P011`) and tube
    `DSG-000005121` (`P521`, on the holder) replace the long jet and ride LJ y.
  - `LIB-000023751` `P343` and `SL201303-02982` `P430`, filed directly under the
    chamber, touch fixed chamber parts and are fixed.
  - Left the design: the long jet, the bottom slit's second blade plate
    `mo39143620`, the ePix10k front plate `mo39134025`, chamber parts
    `DSG-000099332` and `DSG-000052397`, cage parts `DSG-000005038` and
    `LCL5010-008054`.
  - The STEP adds a 0 degree spectrometer copy `A075` and a solid-less 5 degree
    placement `P523`. Relative to the 10 degree mounting they are 10° about world
    −X through (y 0.000, z −19.053) mm and 5° through (y −1.260, z −18.831) mm.
    Both are omitted under their own entry; no viewer selector yet.
- Both packages validate 35 bodies and 34 joints (29 sliders) with 68
  individual endpoints and max pose error 5.55e-16. The convex package has
  7,195 geometries from 400 meshes. CAD-verified home is clear with nothing
  within 1 mm; the cage contact appears at lift −50 mm and clears at home.
- Single-joint sweep, with followers coupled and every pose CAD-verified, onsets
  bisected to 0.01 mm/0.01°; see the README table:
  - Spectrometer vertical −31.38 mm (cage `P534` against envelope `P702`).
  - Analyzer rotation +33.43° (`P1776` against post `P942`).
  - Crystal rotations +17.23°, −34.27°, −35.60°/+44.86°, +16.87°; tilts
    −9.93° (adjacent stacks' `mo39154776` adapters). Exact CAD distances confirm
    crystal 1: 0.094 mm at +17.2°, touching at +17.3°; 0.020 mm at −9.9° tilt.
    The 11-12 table had +23° and clear tilts for the same rigidly moved parts.
  - LJ x +9.52 mm (`P011` against `P413`), LJ z −6.19 mm (tube `P521` against
    `P413`). Slit y −1.62 mm.
  - ePix100 x −6.32/+157.51 mm, tilt −4.95°/+5.09°.
  - Clear: Parker horizontal, crystal translations, LJ y, slit x, all three
    ePix10k stages, ePix100 y and z.

# STEP Revision of 2026-11-12 (SHA-256 `2f9a4891…`)

The review was migrated from the `b1c34cc1…` STEP. References below use the new
manifest; earlier entries use the references of their own revision.

- Mapping: 1,930 occurrences map parent by parent (CAD name without `_oa_`,
  placement within the parent, rigid-shift pairing of moved duplicates). 27 left
  the design and 66 are new. The recipe text was remapped in one pass, keeping its
  comments. Split-template names and history entries were not remapped.
- What moved, in world coordinates:
  - Everything outside chamber assembly `DSG-000102548` moved −67.818 mm in z:
    spectrometer, cage, table and the ePix10k assembly. Every joint frame was
    carried with its stage part's placement change.
  - The ePix10k payload moved +80.115 mm along world Y relative to the lower
    IMS300CC. That restores its 93ae4dc6 placement on the carriage, so
    `moving_offset_mm` is gone and ePix10k z is back to ±150 mm.
  - The ePix100 moved +40.4 mm in z, because its lab jack is now drawn 112.2 mm
    high.
- The long jet `DSG-000022427` is back on the jet adapter, replacing the 14:01 jet
  holder and tube. Its 17 non-fastener parts ride LJ y, as in the 93ae4dc6
  review. `DSG-000004430`, `LIB-000000641`, `LIB-000000666` and the KB1X1 base are
  fixed again.
- The camera rotation stage `LIB-000032933` (`P497`/`P498`) now has solids. It is a
  rotary platform (concentric bearings r 27/34 mm) between camera plates
  `P501` and `P506`, held fixed. `LIB-000032929` is still empty.
- ePix100 stages are multi-part models, so their split templates were removed.
  - **M-EL80 lab jack `LIB-000033108`, a single scissor:**
    - Arms are 103.581 mm between pivots, at 56.24° as drawn.
    - Fixed pivots are at x −233.969 (z −217.074 bottom, −130.963 top); the sliding
      pins at x −176.403; the centre pin at their midpoint.
    - Four follower joints set the arms and blocks from the top plate by the
      scissor relation. The `follows` rule gained `scissor: {arm_m, rise_m,
      output: angle|slide}`, shared by the viewers, collision model and build.
    - Posed in CAD at 53, ~83, 112.2 and 113 mm, every pin stays touching with
      zero overlap.
    - The user asked for Newport's full 53–113 mm, so ePix100 y runs
      −59.211/+0.789 mm.
    - The library CAD is tighter than the real jack:
      - Arm ends cut 36.5 mm³ into the plates' channels at the drawn height
        (clear below −19.68 mm).
      - Arm B meets the top plate below 72.8 mm.
      - The top block meets its channel end at 60.0 mm.

      The 14 parts are an `ignored_groups` entry, a new recipe key that ignores
      every pair inside a group but keeps checking the group against
      everything else.
    - Follower limits are rounded outwards. The scene rejected the arm angle at
      the bottom stop, 2×10⁻¹³ rad past a limit rounded to 12 decimals. The build
      now requires mapped leader limits to fall inside follower limits, and a test
      checks this over every follower's whole leader travel.
  - **VT-50L-13316, the 198 mm version:**
    - The carriage has 203.5 mm between hard stops: 175.5 mm towards the motor,
      where the nut housing meets the motor mount, and 28.0 mm to the far end
      block.
    - With the 198 mm assumed centred in that, it is drawn 73.8 mm from
      mid-travel, and ePix100 x runs −25.22/+172.78 mm.
  - **Manual stage `LIB-000033109`** (base, table, micrometer along world +Y) has
    no end stops in CAD and keeps ±6.5 mm.
  - **Swivel pivot:** the base's guideway arcs and datum sphere `P246` share the
    axis through (y 29.304, z 35.225). The top's arcs sit 0.30 mm lower, a mating
    offset left as drawn.
- Both packages validate 35 bodies and 34 joints (29 sliders), with 68 individual
  endpoints and max pose error 5.55e-16. The convex package has 7,579 geometries;
  CoACD re-ran for 378 of 420 meshes because most parts moved.
- **Home is not clear.** The ePix10k frame `P1751` and plate `P1759` overlap chamber
  part `REF-000062451` `P464` by 4.3 and 1.0 cm³, and the frame's underside is
  15.5 mm below its top. The front plate `P1374` is 0.91 mm from the chamber
  `P546`. The home and ePix10k regressions list the two pairs as `allowed_pairs`,
  and the user was asked whether the 67.8 mm drop is intended.
- Single-joint sweep, with followers coupled and CAD-confirmed onsets bisected
  on their part pairs:
  - Spectrometer vertical: +39.70 mm, Huber base `P965` against ePix100 end
    plate `P228` (new). −37.5 mm as before.
  - Analyzer rotation: +33.03°, ePix10k front plate `P1374` against analyzer post
    `P974`, back now that the payload is upstream again.
  - Crystal rotations: +23°, −35°, −40°, +21°, unchanged.
  - LJ x: +11 mm, unchanged. LJ z: −6.48 mm, long jet `P077` against `P369`.
  - Slit y: −1.72 mm, unchanged.
  - ePix10k z/x/y: blocked from home by the interference. z must move −104.1 mm
    to clear `P464`, and +5 mm reaches the chamber. At y −8 mm the frame also
    drops into the ePix100 breadboard `DSG-000025045` (`P219`), and the mounting
    ribs `P1475`/`P1476` reach `P464`.
  - ePix100 x: −7.05 mm (rear cover against chamber port) and +157.52 mm (manual
    stage base against the VT-50L motor end).
  - ePix100 tilt: −4.96°/+5.09°, arm `P250` against swivel base `P245`, 1.96 mm
    apart at home (2.25 mm before the 0.3 mm swivel offset).
  - Clear: Parker horizontal, crystal translations and tilts, LJ y, slit x,
    ePix100 y (environment only) and ePix100 z.

# ZA16A Wedge Follows ePix10k y (2026-11-11)

Same STEP revision (`b1c34cc1…`). The user pointed out that the ZA16A is a wedge
actuator: the bottom wedge slides forward (up to 29 mm) and is never separated
from the table. The previous entry kept the wedge on the base, so raising y
opened a gap and lowering it drove the table into the wedge.

- The wedge (solid 6) and the rail fixed to it (solid 7, touching it) now form
  body `detector_y_wedge` on `detector_y_wedge_joint`. That joint is prismatic
  along world +Y (local −X), limits ±32 mm, with `follows: {joint:
  detector_y_joint, ratio: 4.0}`.
  - The ratio is the 1/4 wedge: 14.04° incline faces, tan = 0.25.
  - Raising the table drives the wedge forward. At +8 mm its tip (local X −77)
    reaches −109, exactly the "(29)" overhang past the −80 front face that
    Kohzu's drawing dimensions.
- Followers have no slider. `controls.read_followers` and `with_followers` derive
  them from their leader in the motion viewer, and in
  `AssemblyCollisionModel.set_positions`, which the collision viewer, validation
  and its regressions all use. `validate_review` rejects a follower whose leader
  is missing or itself a follower, or whose limits are not ratio × the leader's.
- CAD with the wedge coupled, stepping y over ±8 mm:
  - table-to-wedge and wedge-to-base stay at the drawn 0.500 mm at every height.
    With the wedge held still, the table went to 0 mm (interference) below home
    and opened to 1.4 mm above.
  - `P1719` vs the wedge is 0.787 mm at −8 mm, table vs base 1.4 mm; nothing
    else comes within 2 mm.
- Table and wedge are sibling bodies, so no joint filter covers their bearing;
  `[P1106, P1106]` is a reviewed ignored pair. A hull sweep at 0.5 mm steps
  shows no contacts. New collision regressions put ePix10k y at +8 and −8 mm,
  and both are CAD-verified clear.
- Both packages validate 31 bodies and 30 joints (29 sliders), with 60
  individual endpoints. CoACD ran only for the two re-split ZA16A selections.

# ePix y Stages (2026-11-11)

Same STEP revision (`b1c34cc1…`). The user identified both detectors' vertical
stages.

- ePix10k y, `detector_y_joint`: a Kohzu ZA16A-W2C01 (`P1106`, "L-000000533")
  sits on adapter `P1770` above the upper IMS300CC carriage.
  - The part is Kohzu's own STEP: same bounds and nine solid volumes as the
    vendor download. 14.04° (1/4 wedge) faces identify solid 1 as the table
    (facing down) and solid 6 as the wedge (facing up).
  - The table's top face is at local Z 80.0, the vendor drawing's "80 ± 8", so
    the CAD pose is mid-travel. Limits are ±8 mm along world +Z, with the joint
    origin at the table-top centre (0.02, −474.108, −188.353) mm.
  - Contact walking from the table reaches all 37 other parts that were on
    detector x (frame `P1719` and everything on it); none comes within 1 mm of
    the slide, adapter or ZA16A base. They moved to `detector_y` with the table;
    the base, wedge, roller retainer and feet stay on detector x.
- ePix100 y, `epix100_y_joint`: a manual Newport M-EL80 lab jack (`P328`,
  `DSG-000044951`), drawn as two 8 mm plates of its 80 × 120 mm platform,
  71.775 mm overall.
  - The bottom plate (solid 1) stays fixed; the top plate (solid 2) carries
    adapter `P202` and the whole linear stage. Nothing else touches those parts.
  - Newport lists a 53 mm minimum height and 60 mm travel (113 mm maximum), so
    the limits are −18.775/+41.225 mm along world +Z, assuming the plates are
    drawn at the jack's set height.
- Both packages validate 30 bodies and 29 joints, with 58 individual endpoints,
  max pose error 5.55e-16. CoACD ran for the 43 new or re-bodied selections; the
  convex package has 7,162 geometries. CAD-verified home is clear.
- Single-joint checks, hull sweep with CAD confirmation and CAD conservative
  advancement:
  - ePix10k y: clear over ±8 mm. `P1719` is 8.787 mm above the ZA16A wedge and
    roller retainer at home and 0.787 mm at −8 mm. The wedge's top height does
    not change as it slides, so the margin holds even though the model keeps the
    wedge still. Their hulls touch from −5 mm; `[P1106, P1719]` is a reviewed
    ignored pair.
  - ePix100 y: clear over −18.775/+41.225 mm, with no hull-only contacts.

# LJ y Centred (2026-11-11)

Same STEP revision (`b1c34cc1…`).

- LJ y ran 0 to +8 mm with home at its lower end. That came from the 43841 review,
  which treats the jet lift as assembled fully down. The user confirmed the lift is
  at mid-travel at home, so LJ y is now ±4 mm about the CAD pose, the ZA05A-W101's
  specified travel.
- The geometry agrees. In this STEP the jet lift `LIB-000032469` (`A005`) and both
  slit lifts `LIB-000032451` place their carriage at the library's zero offset on
  the base. Translated down alone, the jet carriage meets its base solidly between
  −5 and −6 mm, the same as the slit carriages (a constant ~60 mm³ sliding
  feature overlaps at every offset and is a reviewed bearing pair). In the older
  43841 STEP every `LIB-000032469` carriage, including the three polycapillary
  lifts, sits 3.105 mm lower. That model was not changed.
- Both packages validate 28 bodies and 27 joints, max pose error 5.55e-16, with no
  geometry rebuilt. CAD-verified home is clear.
- LJ y is clear over ±4 mm in both the hull sweep with CAD confirmation and the CAD
  conservative-advancement check (10 candidate pairs, bearing pair excluded).

# ePix100 Housing (2026-11-06)

Same STEP revision (`b1c34cc1…`).

- The ePix100 module showed only its sensor parts, arm and end plate. Its front and
  rear covers (`P266`/`P222`) and cooling block (`P249`/`P250`) were listed as
  empty source geometry. That was true of the `93ae4dc6…` STEP, but the 14:01
  export gives them solids, and the migration carried the old classification over.
  No other entry in that list had solids.
- The covers and cooling block now ride `epix100_tilt`. So do the parts that stick
  out of the housing's rear face, measured as volume outside the covers' bounding
  box: the Swagelok VCR fittings, tubes and orifice `P251`–`P258`/`P288` (75–100%
  outside), transceiver `P240` (3%) and ribbon cable `P247` (8%). The helicoil
  inserts `P268`/`P270` are omitted as fasteners. Internals fully enclosed by the
  covers stay omitted.
- `validate_review` now requires the empty-geometry list to match the leaves without
  solids exactly, so a re-export that fills in a part stops the build.
- Both packages validate 28 bodies and 27 joints, max pose error 5.55e-16. CoACD
  ran only for the 15 new selections (2 minutes); the convex package has 7,139
  geometries. CAD-verified home is clear (0 touching, 0 within 1 mm).
- Single-joint CAD limits, by conservative advancement over every moving/static pair
  whose swept bounds overlap, bisected to 0.01 mm / 0.005°, are unchanged:
  - ePix100 x: −18.89 mm (`P298` vs `P417`/`P419`). The covers reach the same port
    parts at −19.61/−19.74 mm. +144.94 mm: the Kohzu base against the stage end
    hardware. The rear plumbing clears.
  - ePix100 tilt: −5.48°/+5.74°, arm `P330` against swivel base `P325`.
  - ePix100 z: clear over ±6.5 mm.

# ePix100 Stages (2026-11-05)

Same STEP revision (`b1c34cc1…`).

- The upward-facing ePix100 (`mo39154223` in `DSG-000042618`) now rides three
  joints. The user confirmed the stages: the manual Kohzu translation and the Kohzu
  SH05B-RM swivel.
  - `epix100_x_joint`: lead-screw stage `LIB-000000725` (`P197`), along world X.
  - `epix100_z_joint`: old 70 mm manual Kohzu cross-roller stage `LIB-000005430`
    (`P313`), along world Y.
  - `epix100_tilt_joint`: SH05B-RM swivel `LIB-000013709` (`P325`/`P327`), about
    world X.
- Both translation stages are single fused solids in the STEP. Cross-sections set
  their split masks, and trial Booleans give one moving solid and one fixed solid
  each:
  - linear stage: 47.8 and 232.5 cm³
  - Kohzu: 32.1 and 42.1 cm³

  Two 2 mm³ fragments of the linear stage are dropped by the 100 mm³ rule.
- Payload offset: the adapter `P199`'s M3 counterbores sit 61.19 mm along the travel
  from the fused carriage's tapped holes. The carriage region is offset to match.
  The end blocks allow −92.2/+101.7 mm for the fused carriage, giving −40.51/+153.39
  mm about the CAD pose. The user plans a re-export with the detector mid-travel.
- Swivel pivot: every guideway arc of `P325`/`P327` shares one axis along world X
  through (y 29.308, z −5.162) mm, and datum sphere `P326` is centred on it.
- Kohzu travel: ±6.5 mm, from the XM07A-S1 datasheet (70 × 70 mm, cross-roller,
  13 mm micrometer).
- Both packages validate 28 bodies and 27 joints, with 54 individual endpoints and
  both combined endpoints. The convex package (6,840 geometries) re-ran CoACD only
  for the 18 new or re-bodied selections, taking 2.5 minutes. CAD-verified home is
  clear (0 touching, 0 within 1 mm) and the cage regression still detects its
  contact.
- Sweeps with CAD checks, onsets bisected:
  - ePix100 x: −18.89 mm inward, module `P298` against chamber port parts
    `P417`/`P419`; +144.94 mm outward, Kohzu base against the stage's end hardware
    (9.6 mm gap at home).
  - ePix100 tilt: −5.48°/+5.73°, arm `P330` against swivel base `P325` (2.25 mm
    gap at home).
  - ePix100 z: clear over ±6.5 mm.

# STEP Revision of 2026-11-04 14:01 (SHA-256 `b1c34cc1…`)

The review was migrated from the `93ae4dc6…` STEP. Every reference below uses the
new manifest. Entries further down use the references of their own revision.

- Mapping: 1,889 occurrences map parent by parent, by CAD name without the
  `_oa_` suffix and by placement within the parent.
  - Identical parts that moved together were paired by their common rigid shift:
    0.5 mm spectrometer adjustments and the 80.115 mm ePix z carriage shift.
  - 41 retained parts left the design:
    - the long jet `DSG-000022427`, 19 parts on LJ y
    - the detector module `DSG-000023730`
    - `DSG-000003726`, `DSG-000004430`, `LIB-000000641`, `LIB-000000666` and the
      KB1X1 kinematic base
    - the three RA04A-W rotation stages
- New parts, reviewed by source-CAD contact:
  - Jet holder `P507` (on jet adapter `P011`) and tube `P514` (on `P507`) ride LJ y.
  - `P331` and the post holder set `P508`/`P511`/`P512` (on fixed `P347`) are fixed.
  - Front plate `P1342` (on ePix front ring `P1445`) rides ePix x.
  - The four `LIB-000032444` rotation stages have no solids and are omitted as
    empty geometry, as are the diffractometer body, 2θ arm and 2θ stage.
  - `SA-391-444-50` is not in the STEP.
- Joint frames: each reviewed frame was carried with its stage part's world
  placement. Crystal rotations ride their adapters `mo39185433`, because their
  stages left the design. Crystal translation and rotation origins moved 0.5–1.0 mm
  with the 0.5 mm XA07A shift, and the ePix x frame moved 80.115 mm. Stack 4 frames
  are stack 1's carried by the stack placement transform; predicting stacks 2 and 3
  the same way reproduces their axes exactly and their origins to 0.022 mm.
- ePix z: the payload sits 80.1151 mm along world −Y from the lower IMS300CC's fused
  carriage. The carriage's moving region is offset to sit under it (new
  `moving_offset_mm`), and travel is −69.885/+230.115 mm about the CAD pose.
- Reviewed clearances re-measured in source CAD over full travel, all unchanged:
  - Huber/end plate 0.500 mm
  - Parker bracket 3.250 mm, and ≥ 24.05 mm to the other rail parts
  - slit lift brackets 0.787 mm
  - slit X sensor brackets 0.498 mm
  - chamber port to slit rods ≥ 2.786/2.729 mm
- The new chamber `P513` keeps 4.945 mm from jet adapter `P011`; the previous STEP
  overlapped by 1.1 mm. CAD-verified home is now clear, with 0 touching pairs and 0
  within 1 mm, so the home regressions allow no pairs. The cage contact at lift
  −50 mm (`P526`/`P702`) is still detected.
- Both packages validate 25 bodies and 24 joints: 48 individual endpoints and both
  combined endpoints, with a maximum pose-matrix error of 5.55e-16. The convex
  package has 6,787 hulls over 369 selections, and its 40.7-minute build re-ran
  CoACD for 343 renamed selections.
- Single-joint sweeps, other joints at home: each new hull contact was checked
  against source CAD, and each walk stopped at the first confirmed contact. Steps
  were 1° for rotations, 0.5 mm for jet and slits, 2.5 mm for Parker and crystal
  slides, and 5 mm for the ePix.
  - Contacts:
    - Spectrometer vertical: −37.5 mm (`P526`/`P702`); clear at −25 mm.
    - Crystal rotations against the Thorlabs post `P941`: +23° (stack 1),
      −35° (stack 2), −40° (stack 3), +21° (stack 4).
    - LJ x: +11 mm (`P011`/`P402`).
    - LJ z: −7.5 mm (`P514`/`P402`).
    - Slit lifts: −2.0 mm (`P085`/`P087`, `P134`/`P136`). CAD bisection puts this
      Z-carriage-to-bracket stop at −1.725 mm, ahead of the limit-switch pair
      `P094`/`P103` at −1.83 mm.
    - ePix z: +105 mm (`P1342`/`P513`).
  - Clear over full travel: the horizontal Parker slide, the analyzer (±45°), all
    crystal translations and tilts, LJ y, the slit X stages and ePix x.
  - The analyzer post's previous sweep through the ePix front ring is gone with
    the 80 mm ePix shift.
  - The sweep took 14 minutes; one CAD check on the controls envelope took 476 s.
- Tests: 334 pass. The one failure needs the stale 43841 export on disk and is
  unrelated.

# Limits, Slit Blades, Colours and Home Baseline (2026-11-04)

Measured on the previous STEP revision (SHA-256 `93ae4dc6…`); part references
below use that revision's manifest.

- Analyzer (Huber) and crystal (RA04A) rotations are limited to ±45°. Both packages
  validate 22 bodies and 21 joints: all 42 individual endpoints and both combined
  endpoints match, with a maximum pose-matrix error of 5.55e-16.
- The slit blade holders `P669/P364` and blade plates `P595/P596/P593/P594` now ride
  the slit X stages. The STEP files them under chamber `A003`, but four screws clamp
  each set to its rod tip (see auxiliary-stages.md). The earlier "rods touch
  `DSG-000000720` at −7.5 mm" finding was this ownership error.
- The diffractometer base `P1095` is retained as fixed geometry, with 32 hulls. The
  diffractometer body, 2θ arm and 2θ stage are `SHAPE_REPRESENTATION`s holding only
  `AXIS2_PLACEMENT_3D` supplemental geometry, so they have nothing to draw.
- The STEP has three `NEXT_ASSEMBLY_USAGE_OCCURRENCE`s of `mo39154771`. The fourth
  stack position (+57.9, −15.2 mm in `mo39154770`) is empty in the export.
- STEP face colours: 1,390 of 1,948 leaves carry colours. 89 of the 93 colours
  read back match the sRGB→linear conversion of the STEP `COLOUR_RGB` values, so
  exports convert back to sRGB. All 394 selections have OBJ+MTL visuals. A Drake
  1.55 Meshcat check showed MTL materials taking precedence over the SDF `<diffuse>`.
  Collision source meshes are unchanged: only the 7 new selections ran CoACD
  (7,203 hulls in total).
- Hull-only viewer report after nudging each joint 1 mm or 1° (zero band):
  - Before: 64–72 home contacts reappeared for every joint. Moving the ePix10k
    1 mm showed 72 contacts, none involving it.
  - Now: home contacts stay suppressed while each pair keeps its home relative
    pose. Remaining reports are the LJ axes (the real `P011/P679` STEP overlap and
    `P048`, 0.92 mm CAD gap) and slit lifts at −1 mm. The lift hardware
    `P264/P269/P313/P318` against the X-stage bases is 0.83 mm clear at −1 mm and
    reaches a real stop at −1.83 mm.
  - Raw hull contacts at home: 72 → 13. CAD-verified pairs within 1 mm at home:
    11 → 1.
- Designed running clearances recorded as bearing parts or reviewed ignored pairs
  were measured with source CAD across the full travel; see assembly.yaml notes.
- Live viewer: Bottom slit x −5 mm stays clear. Analyzer rotation +40° reports
  `P1064`/`P1574`, and the CAD check keeps it. A CAD sweep places that contact
  between +33.3° and +43.5°, with the ePix10k at home.
- 100 tests pass in `test_95835_assembly.py` and `test_collision.py`. Ruff is
  clean on the changed files. The collision validator passes all three recipe
  regressions.

# Refined Candidate Validation (2026-09-11)

These results were measured on the previous STEP revision (SHA-256 `c5b38197…`).
Part references below use that revision's manifest, not the current one.

The separate package at `exports/DSG-000095835.candidate/` passed the existing
assembly validator alongside the active baseline. No candidates were promoted.

- Integrated 51 freshly re-audited improved selections; 353 selections retain
  their original hulls. Collision geometry increased from 7,954 to 8,018 hulls.
- All exported hull files match their selected cache hashes. Visual meshes,
  non-collision SDF content, joint metadata, and MATLAB output match the baseline.
  The active export still matches its original cache; a package hash snapshot
  was also checked after both validation runs.
- Both packages pass 13-body/12-joint validation, all 24 individual joint
  endpoints, both combined endpoints, and return home. Maximum pose-matrix
  error is 6.66e-16. Every retained reference remains on its reviewed body,
  and all 68 cage members participate in lift collision checking.
- At home, hull-only false positives fell from five pairs to one:
  `P1177/P1180`. The fixed `parker_cross_P1177_fixed` selection retained its
  original hulls after its resolution-200 trial exhausted the memory limit.
- At vertical lift -50 mm, both packages still detect `P750/P1035` and
  `P750/P1040`. CAD verification retains both contacts and clears home and
  return-home poses. Both packages retain the same four CAD-verified part pairs
  within the 1 mm home warning band.
- Sampled zero-band hull queries took 30-32 ms for the candidate and 29-33 ms
  for the baseline. Cold CAD checks at the 1 mm band took 14.9 and 15.6 seconds,
  respectively. These are individual validation samples, not a benchmark.

The candidate package contains `refinement.json` with source/hull provenance,
`integrity.json` with the package comparison and active-export hash snapshot,
and one `*.validation.json` per package with raw and CAD-verified reports.
The builder integration has 37 passing focused assembly/compiler tests.

Coverage and bulge audits sample the 0.5 mm-deflection CAD tessellation; they do
not prove continuous CAD coverage. Endpoint checks establish kinematics, not
collision-free travel. Contact depths remain hull overlap estimates, not exact
CAD penetration depths. The candidate is validated for these regression poses,
not certified for physical motion.

# Collision Latency (2026-09-10)

- A profiled lift sweep took 9-17 seconds per synchronous check. The viewer then
  waited three times each check's duration before checking another pose, while
  leaving the previous result visible.
- Recipe/statistics data now load once per model. CAD gaps are evaluated and
  cached by relative part pose, so common rigid motion reuses the measurement.
  Relative motion still invalidates it. Containment safeguards are unchanged.
- The shared viewer uses one background worker with a cloned Drake context.
  It discards results for superseded poses, does not queue intermediate poses,
  and no longer delays queries by a multiple of their previous cost. Moving
  clears old highlights and displays `Checking current pose...`; completed
  results include query duration.
- Live browser check: pending feedback appeared in 0.31 s; reset during a
  native CAD operation was accepted in 2.22 s; the obsolete result was discarded
  and the home recheck took 0.03 s. Cage contacts at lift -50 mm appeared in
  0.50 s with a 0.11 s query. Cold home checking still took 14.35 s, so this is
  not a hard real-time detector. Intermediate moving poses can remain unchecked.
- 71 focused tests pass and Ruff is clean. Tests cover private worker context,
  preserved collision filters, stale results, one in-flight query, pending
  readout, common versus relative motion, containment, and the actual assembly's
  clear/contact/clear cage regression.

## Crystal Stacks, Cage Contact, and Display (Earlier)

- The imported manifest contains three `mo39154771` stacks (`A081/A082/A083`).
  All three retained stage chains have distinct cached mesh placements matching
  their CAD bounds. Payloads `P1089/P1133/P1176` are assigned to their respective
  tilt bodies. No fourth stack was present to restore.
- Corrected a missed-collision case in the CAD refinement: OCP measures a 2 mm
  surface gap for a 2 mm box fully inside a 10 mm box when both are compounds,
  but reports zero distance and containment for their constituent solids. The
  refinement now checks those solids before clearing any positive compound gap.
  Regressions cover containment in both directions and a genuinely empty cavity.
- Added recipe-driven contact regressions: CAD home is clear; vertical lift
  -50 mm reports cage member `P750` against controls `P1035/P1040`; returning
  home clears the contacts. These pass with the corrected CAD refinement.
- The validator now verifies each retained reference has illustration and
  proximity geometry on its reviewed body, not just somewhere in the model.
- All 404 illustration meshes use neutral gray. The local viewer starts with
  collision detection enabled and a zero warning band, so clear parts are not
  tinted. Red contacts remain enabled; yellow proximity tint requires increasing
  the warning band.
- Both packages rebuilt; 67 focused tests pass, and Ruff passes for the changed
  Python files. The collision validator passes all body-role ownership checks,
  24 individual joint endpoints, both combined endpoints, and the three
  clear/contact/clear recipe regressions. The two measured cage hull depths at
  -50 mm are 8.48 mm (`P1035`) and 6.28 mm (`P1040`); source-CAD checks retain
  both as contacts. These are diagnostic overlap depths, not exact CAD depths.

## Complete Controls Assembly (Earlier)

- User identified `DSG-000108873` as the XCS Von Hamos Controls assembly,
  correcting its earlier misclassification as a flexible cable carrier.
  All 33 manifest leaves (`P1010` through `P1042`) are now retained, along with
  mounting post `P1043` and rail `P1044`, on `parker_lift`.
- Source-CAD distances: `P1043` touches lift plate `P920`; rail `P1012` touches
  posts `P1043/P1218`; rail `P1044` touches posts `P1209/P1213`. These establish
  the same lift ownership as the previously restored top hardware.
- The recipe now retains 391 leaves and omits 868. A manifest-based regression
  checks that every controls leaf has exactly one owner and is not omitted.
- Both exports rebuilt and passed all 24 individual joint endpoint checks and
  both combined endpoints. All 62 focused assembly/collision/refinement tests
  pass. Drake confirms all 35 restored selections have illustration and proximity
  geometry on the lift. The convex package has 7,954 collision geometries and
  reports zero touching pairs and four pairs within 1 mm at CAD home.
- The current STEP is the user-confirmed 10 degree mounting of `DSG-000095826`
  on `DSG-000097481`. Exact 0 and 5 degree placements remain unverified;
  alternative configuration STEP exports are recommended before enabling them.

## Earlier Electronics and CAD Clearance Correction

- Restored `P1221` and seven rigid support parts previously grouped with the
  omitted flexible cable carrier. Exact CAD distances put posts `P1209`, `P1213`,
  and `P1218` in contact with Parker lift plate `P920`; these parts ride
  `parker_lift`, not the stationary outer cage or rotating analyzer.
- The five convex home-pose overlaps are not source-CAD interferences:
  `P1177` (fixed) / `P1180` has a 0.5 mm gap; `P906` / `P952` has a 3.25 mm
  gap; rotation-stage pairs `P1054` / `P1053`, `P1098` / `P1097`, and
  `P1141` / `P1140` each have a 0.5 mm gap. All five Boolean intersection
  volumes were zero. The additional `P938` / `P955` hull warning has a
  3.25 mm CAD gap.
- The local collision model now checks candidate pairs against body-specific
  reviewed CAD selections, transformed from CAD millimetres using the current
  Drake geometry pose. Only proven gaps above 0.0001 mm clear a hull overlap.
  Zero distance and failed distance queries preserve the conservative hull
  report. No pair is ignored just because it overlaps at home.
- Regression tests cover restored body ownership, hull false positives,
  unchanged-pose caching, rotation and unit conversion, and a clear pair that
  becomes an actual overlap after motion.
- Verification: 61 assembly/collision/refinement tests pass; touched Python files
  pass Ruff. Both exports validate 13 bodies, 12 joints, 24 individual endpoints,
  and both combined endpoints (maximum pose error 6.66e-16). The convex export
  contains 7,187 proximity geometries; all eight restored parts have illustration
  and proximity geometry on `parker_lift`. All 68 cage members remain checked
  against the lift. CAD home reports zero touching pairs and four pairs within
  1 mm. These are clearance checks, not certified collision-free travel limits.

## Earlier Validation Snapshot

# Validation — 2026-09-09

- Source: 1,259 leaf occurrences; 280 retained, 979 explicitly omitted.
- Export: 293 geometric selections on 17 bodies, with 16 scalar joints
  (9 prismatic, 7 revolute).
- Drake loaded both the visual SDF and the hull-collision SDF.
- All 32 individual travel endpoints and both combined endpoint poses matched
  independent rigid-transform calculations. Maximum pose-matrix error was
  6.66 × 10⁻¹⁶, against a 10⁻⁸ tolerance. Zero pose, axes, pivots, limits,
  descendants, and unaffected branches were checked.
- The Meshcat viewer loaded the model and published all 16 controls.
- `test_sdf_compiler.py`, `test_scene.py`, `test_stage_catalog.py`, and
  `test_collision.py`: **59 passed**. Ruff passes for the local Python files.

Representative fixed/moving Boolean partitions had zero intersection volume:

| Stage reference | Selected source volume (mm³) | Removed volume / source |
| --- | ---: | ---: |
| XA07A `P1047` | 394,468.02 | 0.061% |
| SA04B `P1052` | 25,552.00 | 0.443% |
| RA04A `P1054` | 84,675.43 | 0.044% |
| Huber `P1177` | 1,168,706.05 | −0.000061% numerical residual |

The positive removed volumes are disconnected detail/inverted fragments removed
by the 100 mm³ minimum-volume rule. The SA motor/coupling solids are retained
separately on its fixed body. Numerical measurements are in
`.cache/twin_lab/DSG-000095835/split-validation.json`.

The collision smoke check used 293 per-selection convex hulls. At CAD home it
reported 31 touching pairs and 8 additional pairs within 1 mm after restoring
adjacent-link checks. These are diagnostic hull results, not confirmed physical
interferences. No ignored contact pairs were added. Full CoACD decomposition
and physical clearance review were not performed; the optional convex build
command is documented in the assembly README.

The local collision adapter uses explicit `bearing_parts` ownership to retain
Drake's bearing exclusions while reopening payload/support pairs across each
joint. This also checks the first carriage against unrelated static geometry,
which ordinary blanket adjacent-body filtering would hide.
