const outputEl = document.getElementById("output");
const healthEl = document.getElementById("healthStatus");

const locationInput = document.getElementById("locationInput");
const distanceInput = document.getElementById("distanceInput");
const clusterCountInput = document.getElementById("clusterCountInput");

const networkTypeSelect = document.getElementById("networkTypeSelect");
const routingSelect = document.getElementById("routingSelect");
const secondarySelect = document.getElementById("secondarySelect");

const bufferInput = document.getElementById("bufferInput");
const secondaryBufferInput = document.getElementById("secondaryBufferInput");
const meshSpacingInput = document.getElementById("meshSpacingInput");

let lastParcels = [];
let lastClusters = [];
let sourcePoint = { longitude: -97.33, latitude: 32.75 };

const map = L.map("map").setView([32.75, -97.33], 12);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: "&copy; OpenStreetMap contributors",
}).addTo(map);

const parcelLayer = L.layerGroup().addTo(map);
const clusterLayer = L.layerGroup().addTo(map);
const sourceLayer = L.layerGroup().addTo(map);

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
}

map.on("click", (evt) => {
  sourcePoint = { longitude: evt.latlng.lng, latitude: evt.latlng.lat };
  drawSource(sourcePoint);
  log({ source_point: sourcePoint });
});

document.getElementById("fetchParcelsBtn").addEventListener("click", async () => {
  try {
    const payload = {
      location: locationInput.value.trim() || null,
      distance_meters: Number(distanceInput.value),
    };
    const data = await api("/api/parcels/fetch", payload);
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
    const points = lastParcels.map((p) => {
      const g = Array.isArray(p.geometry) ? p.geometry[0] : p.geometry;
      return { longitude: g.longitude, latitude: g.latitude };
    });
    const data = await api("/api/clusters/build", {
      points,
      num_clusters: Number(clusterCountInput.value),
    });
    lastClusters = data.clusters;
    drawClusters(lastClusters);
    log(data);
  } catch (err) {
    log({ error: String(err) });
  }
});

document.getElementById("buildGraphBtn").addEventListener("click", async () => {
  try {
    if (!lastClusters.length) {
      throw new Error("Build clusters first.");
    }
    const data = await api("/api/graph/build", {
      groups: lastClusters.map((c) => ({
        center: c.center,
        points: c.points,
      })),
      source_location: sourcePoint,
      network_type: networkTypeSelect.value,
      routing_strategy: routingSelect.value || null,
      secondary_strategy: secondarySelect.value || null,
      buffer_meters: Number(bufferInput.value),
      secondary_buffer_meters: Number(secondaryBufferInput.value),
      secondary_mesh_spacing_meters: Number(meshSpacingInput.value),
    });
    log(data);
  } catch (err) {
    log({ error: String(err) });
  }
});

document.getElementById("compareBtn").addEventListener("click", async () => {
  try {
    if (!lastClusters.length) {
      throw new Error("Build clusters first.");
    }

    const shared = {
      groups: lastClusters.map((c) => ({ center: c.center, points: c.points })),
      source_location: sourcePoint,
      buffer_meters: Number(bufferInput.value),
      secondary_buffer_meters: Number(secondaryBufferInput.value),
      secondary_mesh_spacing_meters: Number(meshSpacingInput.value),
    };

    const data = await api("/api/graph/compare", {
      builds: [
        {
          ...shared,
          network_type: "balanced_default",
          routing_strategy: null,
          secondary_strategy: null,
        },
        {
          ...shared,
          network_type: "road_optimized",
          routing_strategy: null,
          secondary_strategy: null,
        },
      ],
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
loadOptions().then(checkHealth).catch((err) => log({ error: String(err) }));
