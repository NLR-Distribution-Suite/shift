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

  updateSecondaryControlState();
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

    if (!Number.isFinite(targetAreaSqft) || targetAreaSqft <= 0) {
      throw new Error("Target area per transformer must be a positive number.");
    }
    if (!Number.isFinite(dedicatedAreaSqft) || dedicatedAreaSqft <= 0) {
      throw new Error("Dedicated transformer threshold area must be a positive number.");
    }
    if (!Number.isFinite(targetKva) || targetKva <= 0) {
      throw new Error("Target transformer loading must be a positive number.");
    }
    if (!Number.isFinite(dedicatedLoadKva) || dedicatedLoadKva <= 0) {
      throw new Error("Dedicated transformer threshold load must be a positive number.");
    }
    if (!Number.isFinite(maxSecondaryLengthFt) || maxSecondaryLengthFt <= 0) {
      throw new Error("Max secondary reach must be a positive number.");
    }
    if (!Number.isFinite(numClusters) || numClusters <= 0) {
      throw new Error("Number of clusters must be a positive number.");
    }

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
      transformer_type: document.getElementById("transformerTypeSelect").value,
      transformer_capacity_kva: Number(document.getElementById("transformerCapacityInput").value),
      primary_voltage_kv: Number(document.getElementById("primaryVoltageInput").value),
      secondary_voltage_kv: Number(document.getElementById("secondaryVoltageInput").value),
      catalog_path: document.getElementById("catalogPathInput").value || null,
    };

    log({ building_system: payload.system_name, graph_id: graphId });

    const data = await api("/api/system/build-full", payload);
    log(data);

    if (data.success && data.download_url) {
      const dlBtn = document.getElementById("downloadSystemBtn");
      dlBtn.style.display = "";
      dlBtn.onclick = () => {
        window.open(data.download_url, "_blank");
      };
      // Show fix violations button after successful build
      const fixBtn = document.getElementById("fixViolationsBtn");
      fixBtn.style.display = "";
    }
  } catch (err) {
    log({ error: String(err) });
  }
});

// --- Fix Violations (gdm-flow) ---
document.getElementById("fixViolationsBtn").addEventListener("click", async () => {
  try {
    const systemName = document.getElementById("systemNameInput").value || "my_feeder";
    log({ fixing_violations: systemName, solver: "ldf" });

    const data = await api("/api/system/fix-violations", {
      system_name: systemName,
      max_iterations: 10,
      solver: "ldf",
      vm_min_pu: 0.95,
      vm_max_pu: 1.05,
    });
    log(data);

    if (data.download_url) {
      const dlFixedBtn = document.getElementById("downloadFixedBtn");
      dlFixedBtn.style.display = "";
      dlFixedBtn.onclick = () => {
        window.open(data.download_url, "_blank");
      };
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

// Quick Build button
document.getElementById("quickBuildBtn").addEventListener("click", async () => {
  try {
    if (polygonPoints.length < 3) throw new Error("Draw a polygon first (at least 3 points).");

    const systemName = document.getElementById("qSystemName").value || "my_feeder";
    const catalogPath = document.getElementById("qCatalogPath").value || null;

    document.getElementById("qStatus").textContent = "Fetching parcels...";
    log({ quick_build: "started", system_name: systemName });

    // Try local PBF first, fall back to Overpass
    let parcelResult;
    try {
      parcelResult = await api("/api/parcels/fetch-local", { polygon: polygonPoints });
      log({ parcels_source: "local_pbf", count: parcelResult.count });
    } catch {
      document.getElementById("qStatus").textContent = "Local PBF unavailable, trying Overpass...";
      parcelResult = await api("/api/parcels/fetch", { polygon: polygonPoints });
      log({ parcels_source: "overpass", count: parcelResult.count });
    }

    if (!parcelResult.parcels || !parcelResult.parcels.length) {
      throw new Error("No parcels found in this area.");
    }

    document.getElementById("qStatus").textContent = `${parcelResult.count} parcels → building clusters...`;

    // Cluster
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

    document.getElementById("qStatus").textContent = `${clusterResult.count} clusters → building graph...`;

    // Build graph (offline)
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

    document.getElementById("qStatus").textContent = `Graph: ${graphResult.summary.node_count} nodes → building GDM...`;

    // Build system
    const sysResult = await api("/api/system/build-full", {
      graph_id: graphResult.summary.graph_id,
      system_name: systemName,
      transformer_type: document.getElementById("qTransformerType").value,
      transformer_capacity_kva: Number(document.getElementById("qTransformerKva").value),
      primary_voltage_kv: Number(document.getElementById("qPrimaryKv").value),
      secondary_voltage_kv: Number(document.getElementById("qSecondaryKv").value),
      catalog_path: catalogPath,
    });

    log(sysResult);
    document.getElementById("qStatus").textContent =
      `✓ ${parcelResult.count} parcels → ${clusterResult.count} transformers → ${graphResult.summary.node_count} nodes → GDM exported`;

    if (sysResult.download_url) {
      const dlBtn = document.getElementById("quickDownloadBtn");
      dlBtn.style.display = "";
      dlBtn.onclick = () => window.open(sysResult.download_url, "_blank");
    }
  } catch (err) {
    document.getElementById("qStatus").textContent = "Error — see output";
    log({ error: String(err) });
  }
});

loadOptions().then(checkHealth).catch((err) => log({ error: String(err) }));

// --- Stream backend logs to output panel ---
const logStream = new EventSource("/api/logs/stream");
logStream.onmessage = (event) => {
  const line = event.data;
  if (line) {
    const ts = new Date().toLocaleTimeString();
    outputEl.textContent = `${ts} [server] ${line}\n${outputEl.textContent}`;
  }
};
