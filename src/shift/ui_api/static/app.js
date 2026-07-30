const outputEl = document.getElementById("output");
const healthEl = document.getElementById("healthStatus");
const copyOutputBtn = document.getElementById("copyOutputBtn");
const clearOutputBtn = document.getElementById("clearOutputBtn");

const polygonStartBtn = document.getElementById("polygonStartBtn");
const polygonFinishBtn = document.getElementById("polygonFinishBtn");
const polygonClearBtn = document.getElementById("polygonClearBtn");
const polygonStatus = document.getElementById("polygonStatus");
const pickSourceBtn = document.getElementById("pickSourceBtn");
const resetSourceBtn = document.getElementById("resetSourceBtn");
const sourceStatus = document.getElementById("sourceStatus");
const clusterStrategySelect = document.getElementById("clusterStrategySelect");
const clusterBalanceModeSelect = document.getElementById("clusterBalanceModeSelect");
const clusterCountInput = document.getElementById("clusterCountInput");
const clusterControlHint = document.getElementById("clusterControlHint");
const targetAreaInput = document.getElementById("targetAreaInput");
const dedicatedAreaInput = document.getElementById("dedicatedAreaInput");
const targetKvaInput = document.getElementById("targetKvaInput");
const dedicatedLoadInput = document.getElementById("dedicatedLoadInput");
const maxSecondaryLengthInput = document.getElementById("maxSecondaryLengthInput");

const networkTypeSelect = document.getElementById("networkTypeSelect");
const routingSelect = document.getElementById("routingSelect");
const secondarySelect = document.getElementById("secondarySelect");
const autoSecondaryDensityThresholdInput = document.getElementById(
  "autoSecondaryDensityThresholdInput",
);

const bufferInput = document.getElementById("bufferInput");
const secondaryBufferInput = document.getElementById("secondaryBufferInput");
const meshSpacingInput = document.getElementById("meshSpacingInput");
const targetParcelsPerFeederInput = document.getElementById("targetParcelsPerFeederInput");
const parcelsPerTransformerInput = document.getElementById("parcelsPerTransformerInput");
const minFeedersInput = document.getElementById("minFeedersInput");
const maxFeedersInput = document.getElementById("maxFeedersInput");
const transformerTypeSelect = document.getElementById("transformerTypeSelect");
const transformerCapacityInput = document.getElementById("transformerCapacityInput");
const primaryVoltageInput = document.getElementById("primaryVoltageInput");
const secondaryVoltageInput = document.getElementById("secondaryVoltageInput");
const catalogPathInput = document.getElementById("catalogPathInput");
const transformerOptionSelect = document.getElementById("transformerOptionSelect");
const fixSolverSelect = document.getElementById("fixSolverSelect");
const fixMaxIterationsInput = document.getElementById("fixMaxIterationsInput");
const fixPassesInput = document.getElementById("fixPassesInput");
const fixVmMinInput = document.getElementById("fixVmMinInput");
const fixVmMaxInput = document.getElementById("fixVmMaxInput");
const fixImpedancePresetSelect = document.getElementById("fixImpedancePresetSelect");
const fixImpedanceReductionInput = document.getElementById("fixImpedanceReductionInput");
const autoFixAfterBuild = document.getElementById("autoFixAfterBuild");
const qTransformerTypeSelect = document.getElementById("qTransformerType");
const qTransformerKvaInput = document.getElementById("qTransformerKva");
const qPrimaryKvInput = document.getElementById("qPrimaryKv");
const qSecondaryKvInput = document.getElementById("qSecondaryKv");
const qCatalogPathInput = document.getElementById("qCatalogPath");
const qTransformerOptionSelect = document.getElementById("qTransformerOptionSelect");
const qSystemNameInput = document.getElementById("qSystemName");
const qAutoFixAfterBuild = document.getElementById("qAutoFixAfterBuild");
const qFixSolverSelect = document.getElementById("qFixSolverSelect");
const qFixMaxIterationsInput = document.getElementById("qFixMaxIterationsInput");
const qFixPassesInput = document.getElementById("qFixPassesInput");
const qFixVmMinInput = document.getElementById("qFixVmMinInput");
const qFixVmMaxInput = document.getElementById("qFixVmMaxInput");
const qFixImpedancePresetSelect = document.getElementById("qFixImpedancePresetSelect");
const qFixImpedanceReductionInput = document.getElementById("qFixImpedanceReductionInput");

const clusterBalanceModeLabel = clusterBalanceModeSelect.closest("label");
const clusterCountLabel = clusterCountInput.closest("label");
const targetAreaLabel = targetAreaInput.closest("label");
const dedicatedAreaLabel = dedicatedAreaInput.closest("label");
const targetKvaLabel = targetKvaInput.closest("label");
const dedicatedLoadLabel = dedicatedLoadInput.closest("label");
const maxSecondaryLengthLabel = maxSecondaryLengthInput.closest("label");

const autoSecondaryDensityThresholdLabel = autoSecondaryDensityThresholdInput.closest("label");
const secondaryBufferLabel = secondaryBufferInput.closest("label");
const meshSpacingLabel = meshSpacingInput.closest("label");

const FT_TO_M = 0.3048;
const SQFT_TO_M2 = 0.09290304;

let lastParcels = [];
let lastClusters = [];
let sourcePoint = { longitude: -104.99, latitude: 39.75 };
let polygonPoints = [];
let polygonDrawingActive = false;
let sourcePickingActive = false;
let lastBuiltSystemName = null;
let latestFixedDownloadUrl = null;

const map = L.map("map").setView([39.75, -104.99], 14);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: "&copy; OpenStreetMap contributors",
}).addTo(map);

const parcelLayer = L.layerGroup().addTo(map);
const clusterLayer = L.layerGroup().addTo(map);
const sourceLayer = L.layerGroup().addTo(map);
const polygonLayer = L.layerGroup().addTo(map);
const roadLayer = L.layerGroup().addTo(map);
const graphLayer = L.layerGroup().addTo(map);

function parseNumericInput(value) {
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : NaN;
  }
  const normalized = String(value ?? "")
    .trim()
    .replace(/[,_\s]/g, "");
  if (!normalized) {
    return NaN;
  }
  return Number(normalized);
}

function refreshPolygonOverlay() {
  polygonLayer.clearLayers();

  if (polygonPoints.length >= 2) {
    const linePoints = polygonPoints.map((p) => [p.latitude, p.longitude]);
    L.polyline(linePoints, { color: "#9a3412", weight: 2, dashArray: "4 4" }).addTo(polygonLayer);
  }

  for (const p of polygonPoints) {
    L.circleMarker([p.latitude, p.longitude], {
      radius: 4,
      color: "#9a3412",
      fillColor: "#f97316",
      fillOpacity: 0.85,
    }).addTo(polygonLayer);
  }

  if (polygonPoints.length >= 3) {
    L.polygon(
      polygonPoints.map((p) => [p.latitude, p.longitude]),
      {
        color: "#9a3412",
        weight: 2,
        fillColor: "#fdba74",
        fillOpacity: 0.25,
      },
    ).addTo(polygonLayer);
  }

  polygonStatus.textContent = `Polygon: ${polygonPoints.length} points`;
}

function log(data) {
  outputEl.textContent = `${new Date().toLocaleTimeString()}\n${JSON.stringify(data, null, 2)}\n\n${outputEl.textContent}`;
}

function triggerDownload(downloadUrl) {
  if (!downloadUrl) {
    return;
  }
  const dlWin = window.open(downloadUrl, "_blank");
  if (!dlWin) {
    log({ warning: "Popup blocked while downloading the model zip." });
  }
}

function setLatestFixedDownloadUrl(downloadUrl) {
  latestFixedDownloadUrl = downloadUrl || null;
  const advancedBtn = document.getElementById("downloadFixedBundleBtn");
  const quickBtn = document.getElementById("qDownloadFixedBundleBtn");
  const show = Boolean(latestFixedDownloadUrl);

  if (advancedBtn) {
    advancedBtn.style.display = show ? "" : "none";
  }
  if (quickBtn) {
    quickBtn.style.display = show ? "" : "none";
  }
}

function bindImpedancePreset(presetSelect, factorInput) {
  const presetValues = ["0.95", "0.90", "0.85"];

  presetSelect.addEventListener("change", () => {
    const selected = presetSelect.value;
    if (selected === "custom") {
      return;
    }
    factorInput.value = selected;
  });

  factorInput.addEventListener("input", () => {
    const value = Number(factorInput.value);
    if (!Number.isFinite(value)) {
      return;
    }
    const matched = presetValues.find((v) => Math.abs(Number(v) - value) < 1e-9);
    presetSelect.value = matched || "custom";
  });
}

function validateFixLoopInputs({ vmMinPu, vmMaxPu, impedanceReductionFactor }) {
  if (!Number.isFinite(vmMinPu) || !Number.isFinite(vmMaxPu) || vmMinPu >= vmMaxPu)
    throw new Error("Voltage limits are invalid. Ensure vm_min_pu < vm_max_pu.");
  if (!Number.isFinite(impedanceReductionFactor) || impedanceReductionFactor <= 0 || impedanceReductionFactor >= 1)
    throw new Error("Impedance reduction factor must be > 0 and < 1.");
}

async function runIterativeFixLoop({
  systemName,
  solver,
  maxIterations,
  maxPasses,
  vmMinPu,
  vmMaxPu,
  impedanceReductionFactor,
}) {
  validateFixLoopInputs({ vmMinPu, vmMaxPu, impedanceReductionFactor });

  let selectedSolver = (solver || "ldf").trim().toLowerCase();
  let latestResult = null;

  log({
    fixing_violations: systemName,
    solver: selectedSolver,
    max_iterations: maxIterations,
    max_passes: maxPasses,
    vm_min_pu: vmMinPu,
    vm_max_pu: vmMaxPu,
    impedance_reduction_factor: impedanceReductionFactor,
  });

  for (let pass = 1; pass <= maxPasses; pass += 1) {
    let data;
    try {
      data = await api("/api/system/fix-violations", {
        system_name: systemName,
        output_system_name: systemName,
        max_iterations: maxIterations,
        solver: selectedSolver,
        vm_min_pu: vmMinPu,
        vm_max_pu: vmMaxPu,
        impedance_reduction_factor: impedanceReductionFactor,
      });
    } catch (err) {
      if (selectedSolver === "ldf") {
        log({ warning: "ldf solver failed on this pass, retrying with ac", pass });
        selectedSolver = "ac";
        data = await api("/api/system/fix-violations", {
          system_name: systemName,
          output_system_name: systemName,
          max_iterations: maxIterations,
          solver: selectedSolver,
          vm_min_pu: vmMinPu,
          vm_max_pu: vmMaxPu,
          impedance_reduction_factor: impedanceReductionFactor,
        });
      } else {
        throw err;
      }
    }

    latestResult = data;
    log({
      fix_pass: pass,
      solver: data.solver || selectedSolver,
      success: data.success,
      message: data.message,
      initial_voltage_violations: data.initial_voltage_violations,
      initial_loading_violations: data.initial_loading_violations,
      final_voltage_violations: data.final_voltage_violations,
      final_loading_violations: data.final_loading_violations,
      total_actions: data.total_actions,
    });

    const resolved =
      Number(data.final_voltage_violations || 0) === 0 &&
      Number(data.final_loading_violations || 0) === 0;
    const noActions = Number(data.total_actions || 0) === 0;

    if (resolved) {
      log({ fix_status: "resolved", pass });
      break;
    }
    if (noActions) {
      log({ fix_status: "stalled_no_actions", pass });
      break;
    }
  }

  return latestResult;
}

async function api(path, payload) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.detail || JSON.stringify(data));
  }
  return data;
}

function setSelectOptions(selectEl, options, placeholder) {
  selectEl.innerHTML = "";
  const baseOpt = document.createElement("option");
  baseOpt.value = "";
  baseOpt.textContent = placeholder;
  selectEl.appendChild(baseOpt);

  options.forEach((option, index) => {
    const opt = document.createElement("option");
    opt.value = String(index);
    opt.textContent = option.count > 1 ? `${option.label} (${option.count} available)` : option.label;
    selectEl.appendChild(opt);
  });
}

function applyTransformerOption(option, controls) {
  if (!option) {
    return;
  }
  controls.type.value = option.transformer_type;
  controls.capacity.value = option.transformer_capacity_kva;
  controls.primary.value = option.primary_voltage_kv;
  controls.secondary.value = option.secondary_voltage_kv;
}

async function refreshCatalogTransformerOptions({
  pathInput,
  selectEl,
  controls,
  statusLabel,
}) {
  const catalogPath = pathInput.value.trim();
  if (!catalogPath) {
    setSelectOptions(selectEl, [], "Catalog path required");
    return;
  }

  try {
    const data = await api("/api/catalog/transformers", { catalog_path: catalogPath });
    const options = data.transformers || [];
    if (!options.length) {
      setSelectOptions(selectEl, [], "No matching transformer settings in catalog");
      return;
    }
    selectEl.dataset.options = JSON.stringify(options);
    setSelectOptions(selectEl, options, "Select catalog transformer setting");
    selectEl.value = "0";
    applyTransformerOption(options[0], controls);
    if (statusLabel) {
      statusLabel.textContent = `${options.length} catalog transformer settings loaded`;
    }
  } catch (err) {
    selectEl.dataset.options = "[]";
    setSelectOptions(selectEl, [], "Unable to load catalog settings");
    log({ error: String(err) });
  }
}

function bindCatalogTransformerSelect(selectEl, controls) {
  selectEl.addEventListener("change", () => {
    const options = JSON.parse(selectEl.dataset.options || "[]");
    const index = Number(selectEl.value);
    if (!Number.isInteger(index) || !options[index]) {
      return;
    }
    applyTransformerOption(options[index], controls);
  });
}

async function loadOptions() {
  const res = await fetch("/api/options");
  const data = await res.json();

  for (const val of data.network_types) {
    const opt = document.createElement("option");
    opt.value = val;
    opt.textContent = val;
    networkTypeSelect.appendChild(opt);
  }

  for (const val of data.cluster_strategies || ["kmeans_count", "area_aware"]) {
    const opt = document.createElement("option");
    opt.value = val;
    opt.textContent = val;
    clusterStrategySelect.appendChild(opt);
  }
  clusterStrategySelect.value = "capacity_distance";

  for (const val of data.cluster_balance_modes || ["balanced", "unbalanced"]) {
    const opt = document.createElement("option");
    opt.value = val;
    opt.textContent = val;
    clusterBalanceModeSelect.appendChild(opt);
  }
  clusterBalanceModeSelect.value = "balanced";
  updateClusterControlState();

  const emptyRouting = document.createElement("option");
  emptyRouting.value = "";
  emptyRouting.textContent = "(preset default)";
  routingSelect.appendChild(emptyRouting);

  for (const val of data.routing_strategies) {
    const opt = document.createElement("option");
    opt.value = val;
    opt.textContent = val;
    routingSelect.appendChild(opt);
  }

  const emptySecondary = document.createElement("option");
  emptySecondary.value = "";
  emptySecondary.textContent = "(preset default)";
  secondarySelect.appendChild(emptySecondary);

  for (const val of data.secondary_strategies) {
    const opt = document.createElement("option");
    opt.value = val;
    opt.textContent = val;
    secondarySelect.appendChild(opt);
  }

  if (fixSolverSelect) {
    const flowSolvers = Array.isArray(data.flow_solvers) && data.flow_solvers.length
      ? data.flow_solvers
      : ["ldf", "ac"];
    fixSolverSelect.innerHTML = "";
    for (const val of flowSolvers) {
      const opt = document.createElement("option");
      opt.value = val;
      opt.textContent = val;
      fixSolverSelect.appendChild(opt);
    }
    fixSolverSelect.value = flowSolvers.includes("ldf") ? "ldf" : flowSolvers[0];
    if (qFixSolverSelect) {
      qFixSolverSelect.innerHTML = "";
      for (const val of flowSolvers) {
        const opt = document.createElement("option");
        opt.value = val;
        opt.textContent = val;
        qFixSolverSelect.appendChild(opt);
      }
      qFixSolverSelect.value = flowSolvers.includes("ldf") ? "ldf" : flowSolvers[0];
    }
  }

  updateSecondaryControlState();

  await refreshCatalogTransformerOptions({
    pathInput: catalogPathInput,
    selectEl: transformerOptionSelect,
    controls: {
      type: transformerTypeSelect,
      capacity: transformerCapacityInput,
      primary: primaryVoltageInput,
      secondary: secondaryVoltageInput,
    },
  });

  await refreshCatalogTransformerOptions({
    pathInput: qCatalogPathInput,
    selectEl: qTransformerOptionSelect,
    controls: {
      type: qTransformerTypeSelect,
      capacity: qTransformerKvaInput,
      primary: qPrimaryKvInput,
      secondary: qSecondaryKvInput,
    },
    statusLabel: document.getElementById("qStatus"),
  });
}

function drawParcels(parcels) {
  parcelLayer.clearLayers();
  const points = [];

  parcels.forEach((p) => {
    let lon;
    let lat;
    if (Array.isArray(p.geometry)) {
      lon = p.geometry[0].longitude;
      lat = p.geometry[0].latitude;
    } else {
      lon = p.geometry.longitude;
      lat = p.geometry.latitude;
    }
    points.push([lat, lon]);
    L.circleMarker([lat, lon], { radius: 3, color: "#0f766e" })
      .bindPopup(p.name)
      .addTo(parcelLayer);
  });

  if (points.length) {
    const bounds = L.latLngBounds(points);
    map.fitBounds(bounds.pad(0.15));
  }
}

function drawClusters(clusters) {
  clusterLayer.clearLayers();
  for (const c of clusters) {
    L.circleMarker([c.center.latitude, c.center.longitude], {
      radius: 7,
      color: "#9a3412",
      fillColor: "#fb923c",
      fillOpacity: 0.85,
    })
      .bindPopup(`cluster center (${c.num_points} points)`)
      .addTo(clusterLayer);
  }
}

function drawSource(point) {
  sourceLayer.clearLayers();
  L.marker([point.latitude, point.longitude]).addTo(sourceLayer).bindPopup("Source");
  sourceStatus.textContent = `Source: ${point.longitude.toFixed(5)}, ${point.latitude.toFixed(5)}`;
}

function drawRoads(edges) {
  roadLayer.clearLayers();
  if (!edges || !edges.length) return;
  for (const e of edges) {
    L.polyline(
      [[e.from.latitude, e.from.longitude], [e.to.latitude, e.to.longitude]],
      { color: "#9ca3af", weight: 2, opacity: 0.5, dashArray: "4 2" }
    ).addTo(roadLayer);
  }
}

function drawGraph(geometry) {
  graphLayer.clearLayers();
  if (!geometry) return;

  const edgeColors = {
    DistributionBranchBase: "#2563eb",
    DistributionTransformer: "#dc2626",
  };

  for (const edge of geometry.edges || []) {
    const color = edgeColors[edge.type] || "#6b7280";
    const weight = edge.type === "DistributionTransformer" ? 3 : 2;
    L.polyline(
      [
        [edge.from.latitude, edge.from.longitude],
        [edge.to.latitude, edge.to.longitude],
      ],
      { color, weight, opacity: 0.85 },
    )
      .bindPopup(`${edge.name} (${edge.type})`)
      .addTo(graphLayer);
  }

  for (const node of geometry.nodes || []) {
    const isTransformer = node.name.endsWith("_ht");
    const isSource = node.assets.includes("DistributionVoltageSource");
    const isLoad = node.assets.includes("DistributionLoad");

    let color = "#6b7280";
    let radius = 3;
    let fillColor = "#9ca3af";
    if (isSource) {
      color = "#16a34a";
      fillColor = "#22c55e";
      radius = 7;
    } else if (isTransformer) {
      color = "#dc2626";
      fillColor = "#f87171";
      radius = 5;
    } else if (isLoad) {
      color = "#2563eb";
      fillColor = "#60a5fa";
      radius = 3;
    }

    L.circleMarker([node.location.latitude, node.location.longitude], {
      radius,
      color,
      fillColor,
      fillOpacity: 0.85,
      weight: 1.5,
    })
      .bindPopup(`${node.name}${node.assets.length ? " [" + node.assets.join(", ") + "]" : ""}`)
      .addTo(graphLayer);
  }
}

function updateClusterControlState() {
  const strategy = clusterStrategySelect.value || "kmeans_count";
  const usesExplicitCount = strategy === "kmeans_count";

  clusterCountInput.disabled = !usesExplicitCount;
  clusterBalanceModeSelect.disabled = !usesExplicitCount;

  if (!clusterControlHint) {
    return;
  }

  if (usesExplicitCount) {
    clusterControlHint.textContent = "kmeans_count uses Number of clusters directly.";
  } else if (strategy === "area_aware") {
    clusterControlHint.textContent =
      "area_aware derives cluster count from parcel area thresholds; Number of clusters is ignored.";
  } else if (strategy === "capacity_distance") {
    clusterControlHint.textContent =
      "capacity_distance derives cluster count from loading/reach constraints; Number of clusters is ignored.";
  } else {
    clusterControlHint.textContent = "";
  }

  const showKmeansOnly = strategy === "kmeans_count";
  const showAreaAware = strategy === "area_aware";
  const showCapacityDistance = strategy === "capacity_distance";

  clusterBalanceModeLabel.style.display = showKmeansOnly ? "" : "none";
  clusterCountLabel.style.display = showKmeansOnly ? "" : "none";

  targetAreaLabel.style.display = showAreaAware ? "" : "none";

  dedicatedAreaLabel.style.display = showAreaAware || showCapacityDistance ? "" : "none";
  targetKvaLabel.style.display = showCapacityDistance ? "" : "none";
  dedicatedLoadLabel.style.display = showCapacityDistance ? "" : "none";
  maxSecondaryLengthLabel.style.display = showCapacityDistance ? "" : "none";
}

function updateSecondaryControlState() {
  const secondary = secondarySelect.value || "(preset default)";
  const isPresetDefault = secondary === "(preset default)";
  const isMesh = secondary === "MeshSteinerStrategy";
  const isOpenStreet = secondary === "OpenStreetSecondaryStrategy";
  const isAuto = secondary === "AutoDensitySecondaryStrategy";

  autoSecondaryDensityThresholdLabel.style.display = isAuto ? "" : "none";
  secondaryBufferLabel.style.display = isOpenStreet || isAuto || isPresetDefault ? "" : "none";
  meshSpacingLabel.style.display = isMesh ? "" : "none";
}

map.on("click", (evt) => {
  if (polygonDrawingActive) {
    polygonPoints.push({ longitude: evt.latlng.lng, latitude: evt.latlng.lat });
    refreshPolygonOverlay();
    return;
  }

  if (sourcePickingActive) {
    sourcePoint = { longitude: evt.latlng.lng, latitude: evt.latlng.lat };
    drawSource(sourcePoint);
    sourcePickingActive = false;
    log({ source_point: sourcePoint, source_pick_mode: "completed" });
    return;
  }

  sourcePoint = { longitude: evt.latlng.lng, latitude: evt.latlng.lat };
  drawSource(sourcePoint);
  log({ source_point: sourcePoint });
});

polygonStartBtn.addEventListener("click", () => {
  polygonDrawingActive = true;
  sourcePickingActive = false;
  log({ polygon: "drawing_started" });
});

polygonFinishBtn.addEventListener("click", () => {
  polygonDrawingActive = false;
  if (polygonPoints.length < 3) {
    log({ warning: "Polygon needs at least 3 points." });
    return;
  }
  refreshPolygonOverlay();
  log({ polygon: "closed", points: polygonPoints.length });
});

polygonClearBtn.addEventListener("click", () => {
  polygonDrawingActive = false;
  polygonPoints = [];
  refreshPolygonOverlay();
  log({ polygon: "cleared" });
});

pickSourceBtn.addEventListener("click", () => {
  sourcePickingActive = true;
  polygonDrawingActive = false;
  log({ source_pick_mode: "active", message: "Click map to place source." });
});

resetSourceBtn.addEventListener("click", () => {
  sourcePickingActive = false;
  sourcePoint = { longitude: -97.33, latitude: 32.75 };
  drawSource(sourcePoint);
  log({ source_point: sourcePoint, source_reset: true });
});

document.getElementById("fetchParcelsBtn").addEventListener("click", async () => {
  try {
    if (polygonPoints.length < 3) {
      throw new Error("Create a polygon with at least 3 points.");
    }

    const payload = {
      polygon: polygonPoints,
    };

    // Try local PBF first, then fall back to Overpass
    let data;
    try {
      data = await api("/api/parcels/fetch-local", payload);
      log({ parcels_source: "local_pbf", count: data.count });
    } catch {
      data = await api("/api/parcels/fetch", payload);
      log({ parcels_source: "overpass", count: data.count });
    }

    lastParcels = data.parcels;
    drawParcels(lastParcels);
    log(data);
  } catch (err) {
    log({ error: String(err) });
  }
});

function validateClusterInputs({ targetAreaSqft, dedicatedAreaSqft, targetKva, dedicatedLoadKva, maxSecondaryLengthFt, numClusters }) {
  if (!Number.isFinite(targetAreaSqft) || targetAreaSqft <= 0)
    throw new Error("Target area per transformer must be a positive number.");
  if (!Number.isFinite(dedicatedAreaSqft) || dedicatedAreaSqft <= 0)
    throw new Error("Dedicated transformer threshold area must be a positive number.");
  if (!Number.isFinite(targetKva) || targetKva <= 0)
    throw new Error("Target transformer loading must be a positive number.");
  if (!Number.isFinite(dedicatedLoadKva) || dedicatedLoadKva <= 0)
    throw new Error("Dedicated transformer threshold load must be a positive number.");
  if (!Number.isFinite(maxSecondaryLengthFt) || maxSecondaryLengthFt <= 0)
    throw new Error("Max secondary reach must be a positive number.");
  if (!Number.isFinite(numClusters) || numClusters <= 0)
    throw new Error("Number of clusters must be a positive number.");
}

document.getElementById("clusterBtn").addEventListener("click", async () => {
  try {
    if (!lastParcels.length) {
      throw new Error("Fetch parcels first.");
    }

    const strategy = clusterStrategySelect.value || "kmeans_count";
    const points = lastParcels.map((p) => {
      const g = Array.isArray(p.geometry) ? p.geometry[0] : p.geometry;
      return { longitude: g.longitude, latitude: g.latitude };
    });

    const targetAreaSqft = parseNumericInput(targetAreaInput.value);
    const dedicatedAreaSqft = parseNumericInput(dedicatedAreaInput.value);
    const targetKva = parseNumericInput(targetKvaInput.value);
    const dedicatedLoadKva = parseNumericInput(dedicatedLoadInput.value);
    const maxSecondaryLengthFt = parseNumericInput(maxSecondaryLengthInput.value);
    const numClusters = parseNumericInput(clusterCountInput.value);

    validateClusterInputs({ targetAreaSqft, dedicatedAreaSqft, targetKva, dedicatedLoadKva, maxSecondaryLengthFt, numClusters });

    const payload = {
      strategy,
      balance_mode: clusterBalanceModeSelect.value || "balanced",
      points,
      parcels: lastParcels,
      num_clusters: Math.round(numClusters),
      target_area_per_transformer_m2: targetAreaSqft * SQFT_TO_M2,
      dedicated_transformer_area_m2: dedicatedAreaSqft * SQFT_TO_M2,
      target_kva_per_transformer: targetKva,
      dedicated_transformer_load_kva: dedicatedLoadKva,
      max_secondary_length_m: maxSecondaryLengthFt * FT_TO_M,
    };

    log({
      cluster_request_preview: {
        strategy,
        num_clusters: payload.num_clusters,
        target_area_sqft: targetAreaSqft,
        dedicated_area_sqft: dedicatedAreaSqft,
        target_area_m2: Number(payload.target_area_per_transformer_m2.toFixed(4)),
        dedicated_area_m2: Number(payload.dedicated_transformer_area_m2.toFixed(4)),
      },
    });

    const data = await api("/api/clusters/build", {
      ...payload,
    });
    lastClusters = data.clusters;
    drawClusters(lastClusters);
    log(data);
  } catch (err) {
    log({ error: String(err) });
  }
});

document.getElementById("snapToRoadsBtn").addEventListener("click", async () => {
  const btn = document.getElementById("snapToRoadsBtn");
  try {
    if (!lastClusters.length) {
      throw new Error("Build clusters first.");
    }
    btn.disabled = true;
    btn.textContent = "Snapping...";
    btn.classList.add("loading");

    const data = await api("/api/clusters/snap-to-roads", {
      clusters: lastClusters,
      polygon: polygonPoints.length >= 3 ? polygonPoints : null,
      threshold_m: Number(document.getElementById("snapThresholdInput").value) || 50,
    });
    lastClusters = data.clusters;
    drawClusters(lastClusters);
    btn.textContent = `✓ Snapped ${data.snapped_count}/${data.total}`;
    log(data);
  } catch (err) {
    btn.textContent = "Snap to Roads";
    log({ error: String(err) });
  } finally {
    btn.disabled = false;
    btn.classList.remove("loading");
    setTimeout(() => { btn.textContent = "Snap to Roads"; }, 3000);
  }
});

document.getElementById("buildGraphBtn").addEventListener("click", async () => {
  const btn = document.getElementById("buildGraphBtn");
  try {
    if (!lastClusters.length) {
      throw new Error("Build clusters first.");
    }
    btn.disabled = true;
    btn.textContent = "Building...";
    btn.classList.add("loading");

    const data = await api("/api/graph/build", {
      groups: lastClusters.map((c) => ({
        center: c.center,
        points: c.points,
      })),
      source_location: sourcePoint,
      polygon: polygonPoints.length >= 3 ? polygonPoints : null,
      network_type: networkTypeSelect.value,
      routing_strategy: routingSelect.value || null,
      secondary_strategy: secondarySelect.value || null,
      auto_secondary_density_threshold_per_km2: Number(autoSecondaryDensityThresholdInput.value),
      buffer_meters: Number(bufferInput.value) * FT_TO_M,
      secondary_buffer_meters: Number(secondaryBufferInput.value) * FT_TO_M,
      secondary_mesh_spacing_meters: Number(meshSpacingInput.value) * FT_TO_M,
      snap_threshold_m: Number(document.getElementById("snapThresholdInput").value) || 50,
      crossing_penalty: Number(document.getElementById("crossingPenaltyInput").value) || 1.0,
    });

    // Fetch and draw road network in gray
    try {
      const roadData = await api("/api/roads/network", {
        groups: lastClusters.map((c) => ({ center: c.center, points: c.points })),
        source_location: sourcePoint,
        polygon: polygonPoints.length >= 3 ? polygonPoints : null,
        buffer_meters: Number(bufferInput.value) * FT_TO_M,
      });
      drawRoads(roadData.edges);
    } catch (e) {
      console.warn("Road layer failed:", e);
    }

    drawGraph(data.geometry);
    const s = data.summary || {};
    const radial = s.is_radial ? "✓ Radial" : "✗ Has cycles";
    btn.textContent = `✓ ${s.node_count || ''} nodes`;

    // Show summary bar
    const bar = document.getElementById("graphSummaryBar");
    bar.style.display = "";
    bar.className = `summary-bar ${s.is_radial ? "radial" : "not-radial"}`;
    bar.innerHTML = [
      `<b>${radial}</b>`,
      `Primary: ${s.primary_edges} edges · ${Math.round(s.primary_length_m || 0)}m`,
      `Secondary: ${s.secondary_edges} edges · ${Math.round(s.secondary_length_m || 0)}m`,
      `Transformers: ${s.transformer_hint_count} · Loads: ${s.load_node_count}`,
    ].join("<br>");

    log(data);
  } catch (err) {
    btn.textContent = "Build Graph";
    log({ error: String(err) });
  } finally {
    btn.disabled = false;
    btn.classList.remove("loading");
    setTimeout(() => { btn.textContent = "Build Graph"; }, 3000);
  }
});

document.getElementById("autoBuildFeedersBtn").addEventListener("click", async () => {
  try {
    if (!lastParcels.length) {
      throw new Error("Fetch parcels first.");
    }
    if (polygonPoints.length < 3) {
      throw new Error("Polygon ROI required for density/area-based feeder planning.");
    }

    const data = await api("/api/feeders/auto-build", {
      parcels: lastParcels,
      polygon: polygonPoints,
      network_type: networkTypeSelect.value,
      routing_strategy: routingSelect.value || null,
      secondary_strategy: secondarySelect.value || null,
      auto_secondary_density_threshold_per_km2: Number(autoSecondaryDensityThresholdInput.value),
      buffer_meters: Number(bufferInput.value) * FT_TO_M,
      secondary_buffer_meters: Number(secondaryBufferInput.value) * FT_TO_M,
      secondary_mesh_spacing_meters: Number(meshSpacingInput.value) * FT_TO_M,
      target_parcels_per_feeder: Number(targetParcelsPerFeederInput.value),
      parcels_per_transformer: Number(parcelsPerTransformerInput.value),
      min_feeders: Number(minFeedersInput.value),
      max_feeders: Number(maxFeedersInput.value),
    });
    log(data);
  } catch (err) {
    log({ error: String(err) });
  }
});

async function checkHealth() {
  try {
    const res = await fetch("/api/health");
    const data = await res.json();
    healthEl.textContent = data.status === "ok" ? "API healthy" : "API degraded";
  } catch {
    healthEl.textContent = "API unreachable";
  }
}

drawSource(sourcePoint);
refreshPolygonOverlay();
clusterStrategySelect.addEventListener("change", updateClusterControlState);
secondarySelect.addEventListener("change", updateSecondaryControlState);
copyOutputBtn.addEventListener("click", async () => {
  const text = outputEl.textContent || "";
  if (!text.trim()) {
    return;
  }

  try {
    await navigator.clipboard.writeText(text);
    log({ output: "copied" });
  } catch {
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(outputEl);
    selection.removeAllRanges();
    selection.addRange(range);
    try {
      document.execCommand("copy");
      log({ output: "copied" });
    } finally {
      selection.removeAllRanges();
    }
  }
});
clearOutputBtn.addEventListener("click", () => {
  outputEl.textContent = "";
});

// --- Build & Export GDM System ---
let lastGraphId = null;

// Track graph ID from build
const origBuildHandler = document.getElementById("buildGraphBtn");
// We'll capture graph_id from the log output — simpler: store it from the build response
// Patch: store graph_id when graph is built
const _origFetch = window.fetch;
// Instead, just read from summary variable in the build handler above.

document.getElementById("buildSystemBtn").addEventListener("click", async () => {
  try {
    // Find the latest graph_id from output
    const outputText = outputEl.textContent || "";
    const graphIdMatch = outputText.match(/"graph_id":\s*"([^"]+)"/);
    if (!graphIdMatch) {
      throw new Error("Build a graph first (graph_id not found in output).");
    }
    const graphId = graphIdMatch[1];

    const payload = {
      graph_id: graphId,
      system_name: document.getElementById("systemNameInput").value || "my_feeder",
      transformer_type: transformerTypeSelect.value,
      transformer_capacity_kva: Number(transformerCapacityInput.value),
      primary_voltage_kv: Number(primaryVoltageInput.value),
      secondary_voltage_kv: Number(secondaryVoltageInput.value),
      catalog_path: catalogPathInput.value || null,
    };

    log({ building_system: payload.system_name, graph_id: graphId });

    const data = await api("/api/system/build-full", payload);
    log(data);

    if (data.success && (data.download_bundle_url || data.download_url)) {
      lastBuiltSystemName = payload.system_name;
      // Show fix violations button after successful build
      const fixBtn = document.getElementById("fixViolationsBtn");
      fixBtn.style.display = "";

      let finalDownloadUrl = data.download_bundle_url || data.download_url;
      const shouldAutoFix = Boolean(autoFixAfterBuild?.checked);

      if (shouldAutoFix) {
        const latestResult = await runIterativeFixLoop({
          systemName: payload.system_name,
          solver: fixSolverSelect.value,
          maxIterations: Math.max(1, Number(fixMaxIterationsInput.value) || 10),
          maxPasses: Math.max(1, Number(fixPassesInput.value) || 3),
          vmMinPu: Number(fixVmMinInput.value),
          vmMaxPu: Number(fixVmMaxInput.value),
          impedanceReductionFactor: Number(fixImpedanceReductionInput.value),
        });
        if (latestResult) {
          finalDownloadUrl = latestResult.download_bundle_url || latestResult.download_url || finalDownloadUrl;
          setLatestFixedDownloadUrl(latestResult.download_bundle_url || latestResult.download_url || null);
        }
      }

      // Download the final artifact after build and optional fix loop.
      triggerDownload(finalDownloadUrl);
    }
  } catch (err) {
    log({ error: String(err) });
  }
});

// --- Fix Violations (gdm-flow) ---
document.getElementById("fixViolationsBtn").addEventListener("click", async () => {
  try {
    const systemName =
      lastBuiltSystemName ||
      document.getElementById("systemNameInput").value ||
      qSystemNameInput.value ||
      "my_feeder";

    const maxIterations = Math.max(1, Number(fixMaxIterationsInput.value) || 10);
    const maxPasses = Math.max(1, Number(fixPassesInput.value) || 3);
    const vmMinPu = Number(fixVmMinInput.value);
    const vmMaxPu = Number(fixVmMaxInput.value);
    const latestResult = await runIterativeFixLoop({
      systemName,
      solver: fixSolverSelect.value,
      maxIterations,
      maxPasses,
      vmMinPu,
      vmMaxPu,
      impedanceReductionFactor: Number(fixImpedanceReductionInput.value),
    });

    if (latestResult) {
      const downloadUrl = latestResult.download_bundle_url || latestResult.download_url;
      setLatestFixedDownloadUrl(downloadUrl || null);
      triggerDownload(downloadUrl);
    }
  } catch (err) {
    log({ error: String(err) });
  }
});

// --- Mode Toggle ---
const advancedPanel = document.getElementById("advancedPanel");
const quickPanel = document.getElementById("quickPanel");
const modeAdvancedBtn = document.getElementById("modeAdvancedBtn");
const modeQuickBtn = document.getElementById("modeQuickBtn");

modeAdvancedBtn.addEventListener("click", () => {
  advancedPanel.style.display = "";
  quickPanel.style.display = "none";
  modeAdvancedBtn.classList.add("active");
  modeQuickBtn.classList.remove("active");
});
modeQuickBtn.addEventListener("click", () => {
  advancedPanel.style.display = "none";
  quickPanel.style.display = "";
  modeQuickBtn.classList.add("active");
  modeAdvancedBtn.classList.remove("active");
});

// Quick-build polygon/source reuse the same state
document.getElementById("qPolygonStartBtn").addEventListener("click", () => {
  polygonDrawingActive = true;
  sourcePickingActive = false;
  log({ polygon: "drawing_started" });
});
document.getElementById("qPolygonFinishBtn").addEventListener("click", () => {
  polygonDrawingActive = false;
  if (polygonPoints.length < 3) {
    log({ warning: "Polygon needs at least 3 points." });
    return;
  }
  refreshPolygonOverlay();
  document.getElementById("qStatus").textContent = `Polygon: ${polygonPoints.length} pts. Click source icon then map.`;
  log({ polygon: "closed", points: polygonPoints.length });
});
document.getElementById("qPolygonClearBtn").addEventListener("click", () => {
  polygonDrawingActive = false;
  polygonPoints = [];
  refreshPolygonOverlay();
  document.getElementById("qStatus").textContent = "Draw polygon, then pick source";
  log({ polygon: "cleared" });
});
document.getElementById("qPickSourceBtn").addEventListener("click", () => {
  sourcePickingActive = true;
  polygonDrawingActive = false;
  document.getElementById("qStatus").textContent = "Click map to place source...";
  log({ source_pick_mode: "active" });
});

// Configure local PBF
document.getElementById("qConfigPbfBtn").addEventListener("click", async () => {
  const pbfPath = document.getElementById("qPbfPath").value;
  try {
    const result = await api("/api/config/local-pbf", { pbf_path: pbfPath });
    document.getElementById("qPbfStatus").textContent = "✓ PBF ready";
    log(result);
  } catch (err) {
    document.getElementById("qPbfStatus").textContent = "✗ " + String(err).slice(0, 60);
    log({ error: String(err) });
  }
});

async function fetchParcelsForQuickBuild(polygonPoints) {
  try {
    const result = await api("/api/parcels/fetch-local", { polygon: polygonPoints });
    log({ parcels_source: "local_pbf", count: result.count });
    return result;
  } catch {
    const result = await api("/api/parcels/fetch", { polygon: polygonPoints });
    log({ parcels_source: "overpass", count: result.count });
    return result;
  }
}

async function buildQuickGraphAndSystem({ polygonPoints, sourcePoint, systemName, catalogPath, parcelResult, qTransformerTypeSelect, qTransformerKvaInput, qPrimaryKvInput, qSecondaryKvInput }) {
  const SQFT_TO_M2 = 0.09290304;
  const clusterResult = await api("/api/clusters/build", {
    strategy: "area_aware",
    parcels: parcelResult.parcels,
    points: parcelResult.parcels.map(p => {
      const g = Array.isArray(p.geometry) ? p.geometry[0] : p.geometry;
      return { longitude: g.longitude, latitude: g.latitude };
    }),
    target_area_per_transformer_m2: 54000 * SQFT_TO_M2,
    dedicated_transformer_area_m2: 22000 * SQFT_TO_M2,
    num_clusters: 5,
  });

  const graphResult = await api("/api/graph/build", {
    groups: clusterResult.clusters.map(c => ({ center: c.center, points: c.points })),
    source_location: sourcePoint,
    polygon: polygonPoints,
    network_type: "balanced_default",
    secondary_strategy: "DelaunayStrategy",
    buffer_meters: 20,
    secondary_buffer_meters: 50,
    offline: true,
  });

  if (graphResult.geometry) drawGraph(graphResult.geometry);

  const sysResult = await api("/api/system/build-full", {
    graph_id: graphResult.summary.graph_id,
    system_name: systemName,
    transformer_type: qTransformerTypeSelect.value,
    transformer_capacity_kva: Number(qTransformerKvaInput.value),
    primary_voltage_kv: Number(qPrimaryKvInput.value),
    secondary_voltage_kv: Number(qSecondaryKvInput.value),
    catalog_path: catalogPath,
  });

  return { clusterResult, graphResult, sysResult };
}

// Quick Build button
document.getElementById("quickBuildBtn").addEventListener("click", async () => {
  try {
    if (polygonPoints.length < 3) throw new Error("Draw a polygon first (at least 3 points).");

    const systemName = qSystemNameInput.value || "my_feeder";
    const catalogPath = qCatalogPathInput.value || null;

    document.getElementById("qStatus").textContent = "Fetching parcels...";
    log({ quick_build: "started", system_name: systemName });

    const parcelResult = await fetchParcelsForQuickBuild(polygonPoints);

    if (!parcelResult.parcels || !parcelResult.parcels.length) {
      throw new Error("No parcels found in this area.");
    }

    document.getElementById("qStatus").textContent = `${parcelResult.count} parcels → building clusters...`;

    const { clusterResult, graphResult, sysResult } = await buildQuickGraphAndSystem({
      polygonPoints, sourcePoint, systemName, catalogPath, parcelResult,
      qTransformerTypeSelect, qTransformerKvaInput, qPrimaryKvInput, qSecondaryKvInput,
    });

    log(sysResult);
    document.getElementById("qStatus").textContent =
      `✓ ${parcelResult.count} parcels → ${clusterResult.count} transformers → ${graphResult.summary.node_count} nodes → GDM exported`;

    lastBuiltSystemName = systemName;
    const fixBtn = document.getElementById("fixViolationsBtn");
    fixBtn.style.display = "";
    const qFixBtn = document.getElementById("qFixViolationsBtn");
    qFixBtn.style.display = "";

    let finalDownloadUrl = sysResult.download_bundle_url || sysResult.download_url;
    const shouldAutoFix = Boolean(qAutoFixAfterBuild?.checked);

    if (shouldAutoFix) {
      document.getElementById("qStatus").textContent = "Running iterative power-flow fix...";
      const latestResult = await runIterativeFixLoop({
        systemName,
        solver: qFixSolverSelect.value,
        maxIterations: Math.max(1, Number(qFixMaxIterationsInput.value) || 10),
        maxPasses: Math.max(1, Number(qFixPassesInput.value) || 3),
        vmMinPu: Number(qFixVmMinInput.value),
        vmMaxPu: Number(qFixVmMaxInput.value),
        impedanceReductionFactor: Number(qFixImpedanceReductionInput.value),
      });
      if (latestResult) {
        finalDownloadUrl = latestResult.download_bundle_url || latestResult.download_url || finalDownloadUrl;
        setLatestFixedDownloadUrl(latestResult.download_bundle_url || latestResult.download_url || null);
      }
      document.getElementById("qStatus").textContent = "Fix loop complete. Downloading model bundle...";
    }

    if (finalDownloadUrl) {
      // Download final model artifact after build (and optional fix passes).
      triggerDownload(finalDownloadUrl);
    }
  } catch (err) {
    document.getElementById("qStatus").textContent = "Error — see output";
    log({ error: String(err) });
  }
});

document.getElementById("qFixViolationsBtn").addEventListener("click", async () => {
  try {
    const systemName =
      lastBuiltSystemName ||
      qSystemNameInput.value ||
      document.getElementById("systemNameInput").value ||
      "my_feeder";
    const latestResult = await runIterativeFixLoop({
      systemName,
      solver: qFixSolverSelect.value,
      maxIterations: Math.max(1, Number(qFixMaxIterationsInput.value) || 10),
      maxPasses: Math.max(1, Number(qFixPassesInput.value) || 3),
      vmMinPu: Number(qFixVmMinInput.value),
      vmMaxPu: Number(qFixVmMaxInput.value),
      impedanceReductionFactor: Number(qFixImpedanceReductionInput.value),
    });
    if (latestResult) {
      const downloadUrl = latestResult.download_bundle_url || latestResult.download_url;
      setLatestFixedDownloadUrl(downloadUrl || null);
      triggerDownload(downloadUrl);
    }
  } catch (err) {
    log({ error: String(err) });
  }
});

document.getElementById("downloadFixedBundleBtn").addEventListener("click", () => {
  if (!latestFixedDownloadUrl) {
    log({ warning: "No fixed model bundle available yet. Run iterative fix first." });
    return;
  }
  triggerDownload(latestFixedDownloadUrl);
});

document.getElementById("qDownloadFixedBundleBtn").addEventListener("click", () => {
  if (!latestFixedDownloadUrl) {
    log({ warning: "No fixed model bundle available yet. Run iterative fix first." });
    return;
  }
  triggerDownload(latestFixedDownloadUrl);
});

loadOptions().then(checkHealth).catch((err) => log({ error: String(err) }));

bindImpedancePreset(fixImpedancePresetSelect, fixImpedanceReductionInput);
bindImpedancePreset(qFixImpedancePresetSelect, qFixImpedanceReductionInput);

bindCatalogTransformerSelect(transformerOptionSelect, {
  type: transformerTypeSelect,
  capacity: transformerCapacityInput,
  primary: primaryVoltageInput,
  secondary: secondaryVoltageInput,
});

bindCatalogTransformerSelect(qTransformerOptionSelect, {
  type: qTransformerTypeSelect,
  capacity: qTransformerKvaInput,
  primary: qPrimaryKvInput,
  secondary: qSecondaryKvInput,
});

catalogPathInput.addEventListener("change", () =>
  refreshCatalogTransformerOptions({
    pathInput: catalogPathInput,
    selectEl: transformerOptionSelect,
    controls: {
      type: transformerTypeSelect,
      capacity: transformerCapacityInput,
      primary: primaryVoltageInput,
      secondary: secondaryVoltageInput,
    },
  }),
);

qCatalogPathInput.addEventListener("change", () =>
  refreshCatalogTransformerOptions({
    pathInput: qCatalogPathInput,
    selectEl: qTransformerOptionSelect,
    controls: {
      type: qTransformerTypeSelect,
      capacity: qTransformerKvaInput,
      primary: qPrimaryKvInput,
      secondary: qSecondaryKvInput,
    },
    statusLabel: document.getElementById("qStatus"),
  }),
);

// --- Stream backend logs to output panel ---
const logStream = new EventSource("/api/logs/stream");
logStream.onmessage = (event) => {
  const line = event.data;
  if (line) {
    const ts = new Date().toLocaleTimeString();
    outputEl.textContent = `${ts} [server] ${line}\n${outputEl.textContent}`;
  }
};
