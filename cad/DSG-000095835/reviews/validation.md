# Electronics and CAD clearance correction (2026-09-10)

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
