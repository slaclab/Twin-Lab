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
