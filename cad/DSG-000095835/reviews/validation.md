# Refined Candidate Validation (2026-09-11)

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
