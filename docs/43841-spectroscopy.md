# Beamline guide: 43841 flat-analyzer spectroscopy preview

```bash
uv run slac-run 43841 --spectroscopy
```

Run this from the Twin Lab repository root after [setup](../README.md#setup).
This mode needs the reviewed `cad/DSG-000040389/source.stp`. It uses the motion
geometry cache, not the published collision bundle. The first launch may need
to prepare the CAD. Open the printed Meshcat URL and look for **ePix100
spectroscopy preview**. This mode does not connect to motors or check clearance.
The **Lower Slit** and **Upper Slit** stages are shown in the regular motion
viewer, but their geometry and controls are omitted from spectroscopy mode.

1. **Choose the emitted photon energy.** Start with **Pt Lα1 (9442.3 eV)** and
   **Graphite(004)**, or try **Fe Kα1 (6403.84 eV)** and **Graphite(004)** or
   **Graphite(002)**. These are benchmarks in Table 3 of the
   [published PCXS paper][pcxs]; they do not establish which crystals are
   installed. For partial-fluorescence-yield XAS, use the fluorescence line here,
   not the incident absorption-edge energy (e.g. 11564 eV for the Pt L3 edge).
2. **Find a starting pose.** Click **Find starting poses** to test up to four
   compatible named reflections. Select the Graphite(004) result for the Pt
   example. Review **Before**, **Proposed**, and the slider changes; click
   **Apply to simulator** to load that pose and reflection. **Auto-align
   preview** instead holds the selected reflection and searches for all three
   beams. Neither action updates the stage sliders until you apply the proposal.
3. **Place the spot on the detector.** Once you have a live spot, edit
   **Target u** or **Target v** and press Enter or leave the field. This moves
   the existing **A205** (u) or **A206** (v) LX10 slider and the detector in
   the 3D view, without moving the crystals or the **A204** depth stage.
   The move uses the current centroid and is limited to ±12.5 mm of stage
   travel. Near the sensor edge, clipping can shift the centroid; check the
   live image. If no spot is detected, the detector stays put. You can still
   drag either LX10 slider directly.
4. **Check the fluorescence band at that pose.** Enter **Below line** and
   **Above line**, then click **Compare reflections here**. **All 3 ≥80%**
   counts the sampled energies at which each crystal delivers at least 80% of
   its Bragg-accepted rays to the modeled sensor. Compare the North, Middle and
   South coverage strips and the closest captured ray's edge margin. Rerun the
   check after changing the optical pose or Bragg half-width.

When dragging the detector, crystal, or polycapillary sliders, the live image
can stay dark if no Bragg rays reach the sensor. Colored aiming guides show the
beam axes projected onto the sensor plane, even if they miss the crystal or
are outside the Bragg window. Arrows point toward off-sensor projections. These
guides never count as hits and can be turned off.

The model starts parallel rays at each reviewed polycapillary exit and clips
them against the front face of the **70 × 30 mm** plate inside each STEP holder.
The colored outline and cross mark each plate's boundary and center; the lines
show individual rays, so they need not all pass through the cross. The nominal
ePix100 rectangle is at the CAD housing nose; the active chip position has not
been measured in this model. **Hits / accepted** counts modeled rays, not photons.
An accepted ray reaches a crystal within the assumed Bragg window; a hit also reaches the
modeled sensor. Flat crystals do not focus like the [95835 analyzers](95835-spectroscopy.md).
The default **±0.10°** Bragg window is a simulation setting, not a measured
rocking curve or a calibration of the paper's HAPG/HOPG results.

### Which polycapillaries?

The [PCXS paper][pcxs] identifies **XOS** as the supplier of the 80 mm short
and 90 mm long optics. All three 43841 CAD paths use optic `REF-000221282`,
in assembly `REF-000221283` with housing `REF-000221284`. The CAD assembly
measures **90 mm end to end**, consistent with the long design. These are
SLAC CAD identifiers, not an XOS order number; check the Teamcenter record
for `REF-000221283` or the optic label before assuming the installed part
matches the drawing.

The trace uses a **20 mm** sampled beam at the CAD exit, not an XOS optical
prescription. For comparison, Table 2 reports **1.9 mrad** at the Fe K edge
and **1.7 mrad** at the Pt L3 edge for the long optic. The simulation does not
use those values or model the measured focal response or throughput.
The XOS *Polycapillary X-ray Optics for Micro XRF and XRD* datasheet gives
an example of **0.2°** output divergence at **8 keV** for the collimating
family; it does not identify this particular optic or specify its divergence.

The model does not predict absolute intensity or spectral resolution. It does
not model polycapillary focus at the sample or beam divergence, graphite
mosaicity or reflectivity, detector gaps, photodiode capture, or obstructions.
Confirm the installed optics, detector position, clearance, and real stage
coordinates independently before using a proposed pose at the beamline.

[pcxs]: https://doi.org/10.1021/photonsci.5c00024
