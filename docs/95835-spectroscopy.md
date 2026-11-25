# Beamline guide: 95835 von Hamos spectroscopy preview

Use Twin Lab before beamtime to ask: **Which analyzer reflection is worth
trying, where might the line land on the ePix100, and will the energy band I
need fit?** The model uses four 250 mm-radius analyzers. It is an offline
planning tool: it does not connect to motors or check clearance. Treat its
poses as ideas to verify, not motor setpoints.

## Open the preview

From the Twin Lab repository root on Linux or WSL:

```bash
uv run slac-run 95835 --spectroscopy
```

For a new installation, follow [Twin Lab setup](../README.md#setup) and ask the
model maintainer for the **reviewed 95835 STEP**. It is not included in the
repository; place it at `cad/DSG-000095835/source.stp`. If the viewer reports a
revision mismatch, use the reviewed file rather than a newer export. First
launch prepares local geometry; later launches reuse the cache.
Open the Meshcat URL printed in the terminal if the browser does not open
automatically. Look for **ePix100 spectroscopy preview**.

## 1. Find a starting pose

1. Select the **Emission line**. For a first run, try **Fe K&beta;1,3
   (7058.2 eV)**, based on the [published XCS Fe setup][fe-setup].
2. Click **Find starting poses**. This can recover signal from a blank
   detector. It tests up to four compatible reflections, even if a different
   reflection is selected. It tries matching Fe or Co references first; the
   rest of the shortlist is based on Bragg angle, not proven reachability.
3. Use **Ranked starting poses** to review candidates. The search favors
   signal from all four crystals but can return partial results. For the Fe
   example, inspect the **Ge(620)** candidate. A crystal counts as having
   signal in this search at 32 or more modeled hits, not 32 measured photons.
4. Compare **Before** and **Proposed**, including the hit counts and spot
   widths. Open **Proposed slider changes** if you want to inspect the offsets.
   Click **Apply to simulator** to load the pose and its reflection.
   Previewing or cancelling a search moves nothing.

If you already know which analyzers you will use, select that reflection in
**Reflection for all four crystals** and click **Auto-align preview** instead.
This keeps the selected reflection and looks for a shared spot with signal from
all four crystals. **Target u / v** defaults to the detector center. Enter an
offset in mm if you want the line elsewhere on the sensor (positive **u** is
right; positive **v** is up). Changing the pose, optics, or target invalidates a
pending preview; rerun it before applying.

## 2. Check the energy band at that pose

1. Open **Check energy band**. After applying a pose, **Check band at this
   pose** opens the same section.
2. Set **Below line (eV)** and **Above line (eV)** to bracket the features you
   need. For the Fe example, **Use published Fe band** fills in
   **7030&ndash;7125 eV**.
3. Click **Compare reflections here**. This tests all named presets at the
   **current pose**, not at a separately optimized pose for each reflection.
   It checks 21 evenly spaced energies including both endpoints, or just the
   line if both offsets are zero. No stages move.
4. Select a reflection row. Read **All 4 &ge;80%** first: it counts sampled
   energies where **each** crystal lands at least 80% of its Bragg-accepted
   rays on the modeled sensor. **Any hit** only means at least one crystal
   landed a ray at that energy. The published Fe precedent is listed first
   when applicable, even if another row scores better at your current pose.
5. Inspect the four coverage strips, especially at the band edges. Green is
   at least 80% capture, amber is partial, red means the accepted rays miss
   the sensor, and gray means no accepted rays. The detector map shows
   centroids, not spot outlines. Check the closest captured ray's distance
   to the modeled edge as well: a centered centroid can hide clipping.

**Use reflection in simulator** changes only the reflection. If you change a
stage, use auto-align, or change the Bragg half-width, run **Compare reflections
here** again. A sharp line at one energy does not guarantee that the rest of
the band fits.

## Read the single-line preview

| What you see | How to use it |
| --- | --- |
| Gold cross and cyan ring | The target and the weighted centroid, respectively. Compare both RMS widths and the per-crystal hit counts before calling a spot well focused. |
| **Hits / accepted** | The numerator landed on the modeled sensor; the denominator passed the Bragg window. `0 / N` with `N > 0` means the detector misses those rays. `0 / 0` means none passed the Bragg window at that pose. |
| **Best effort only** | Target error or at least one RMS width exceeds 0.5 mm. This is a simulator criterion, not a beamline tolerance. |
| Horizontal travel limit | The preview could not finish centering in **u** within ePix100 x travel. The simulated x lower limit is **-6.5 mm**. |
| No compatible reflection or no better pose | An impossible Bragg angle rules out that line/spacing/order. With an allowed angle, a failed search does not rule out a usable pose. Try a different reflection, starting pose, or on-sensor target. |

Use the Meshcat stage sliders to investigate an offset, and **Reset to home**
to restore the CAD stage pose. Keep **Bragg half-width** at its default
&plusmn;0.05&deg; for comparisons unless you deliberately want to test
sensitivity to that assumption. Images are normalized separately, so a
brighter image does not mean more signal.

## Use your own line or analyzer parameters

- For a measured line or a sample-specific valence-to-core feature, select
  **Custom energy** and set **Custom emission energy (eV)** in Meshcat. The
  [NIST-based presets][nist] are nominal energies, not measured sample peaks.
- Named reflections already specify their lattice planes and use order 1.
  To enter a different spacing and order, select **Custom d-spacing / order**,
  set **Custom d-spacing (angstrom)** and **Custom Bragg order**, then use
  **Auto-align preview**. **Find starting poses** and **Compare reflections
  here** test named reflections only.
- Fe K&beta;1,3 with **Ge(620)** is a [published XCS example][fe-setup].
  The Co setup notes list **Si(533)** for K&beta;1,3 (~7649 eV) and
  **Ge(444)** for valence-to-core K&beta;2,5 (~7705 eV), both at 250 mm
  radius. The Mn **Si(440)** precedent is from a [different, 16-crystal
  LCLS instrument][mn-precedent]. None of these entries confirms what is
  installed or available. Custom d-spacing changes diffraction, not crystal
  curvature: a 500 mm analyzer is not represented by this model.

## Before taking a result to the beamline

Record the line energy, requested band, reflection, Bragg half-width, CAD
revision, and proposed slider offsets. Save the per-crystal coverage and edge
margin as well as the spot image. The model uses a fixed point source, a simple
Bragg window (not a measured rocking curve), and a continuous detector
rectangle. It does not model detector gaps, reflectivity, absolute counts,
or spectral resolution. Capture is a fraction of simulated rays, and the band
check is discrete. Confirm the installed analyzer and detector configuration,
verify clearance and stage coordinates independently, and check the line and
band against measured data before using the result to plan moves.

[fe-setup]: https://doi.org/10.3390/molecules29102323
[nist]: https://www.nist.gov/pml/x-ray-transition-energies-database
[mn-precedent]: https://biology-lcls.slac.stanford.edu/capabilities/spectroscopy
