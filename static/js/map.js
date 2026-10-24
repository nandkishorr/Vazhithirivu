(function () {
  "use strict";

  const cfgEl = document.getElementById("map-config");
  const loadingEl = document.getElementById("map-loading");
  const apiErrEl = document.getElementById("map-api-error");

  // No map-config element: Google Maps isn't configured; the server already
  // rendered the not-configured state.
  if (!cfgEl) return;

  const cfg = JSON.parse(cfgEl.textContent);
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const coarsePointer = window.matchMedia("(pointer: coarse)").matches;

  function showApiError(message) {
    if (loadingEl) loadingEl.hidden = true;
    if (apiErrEl) {
      const body = apiErrEl.querySelector("[data-error-body]");
      if (body && message) body.textContent = message;
      apiErrEl.hidden = false;
    }
  }

  window.gm_authFailure = function () {
    showApiError("Google Maps couldn't authorise this key. Check the browser key and its restrictions.");
  };

  window.vz = { map: null, AdvancedMarkerElement: null, userMarker: null };

  function setupAutocomplete(PlaceAutocompleteElement) {
    [
      ["id_origin", "origin", "origin_place_id"],
      ["id_destination", "destination", "destination_place_id"],
    ].forEach(([inputId, fieldName, hiddenName]) => {
      const input = document.getElementById(inputId);
      if (!input) return;
      const el = new PlaceAutocompleteElement({
        includedRegionCodes: ["in"],
        locationBias: {
          radius: 50000,
          center: { lat: cfg.center[0], lng: cfg.center[1] },
        },
      });
      el.setAttribute("placeholder", input.getAttribute("placeholder") || "");
      const label = document.querySelector('label[for="' + inputId + '"]');
      if (label) el.setAttribute("aria-label", label.textContent.trim());
      el.className = "block w-full";

      const hidden = document.createElement("input");
      hidden.type = "hidden";
      hidden.name = hiddenName;
      hidden.id = "id_" + hiddenName;

      input.classList.add("hidden");
      input.setAttribute("aria-hidden", "true");
      input.tabIndex = -1;
      input.parentElement.appendChild(el);
      input.parentElement.appendChild(hidden);

      el.addEventListener("gmp-select", async (event) => {
        const place = event.placePrediction.toPlace();
        await place.fetchFields({
          fields: ["id", "displayName", "formattedAddress", "location"],
        });
        const name =
          typeof place.displayName === "string"
            ? place.displayName
            : (place.displayName && place.displayName.text) || "";
        input.value = place.formattedAddress || name;
        hidden.value = place.id || "";
      });
    });
  }

  // --- Crossing markers ------------------------------------------------------
  const PIN_NEUTRAL = { background: "#64748b", borderColor: "#475569", glyphColor: "#ffffff" };
  const PIN_SELECTED = { background: "#0f172a", borderColor: "#020617", glyphColor: "#ffffff" };

  function setupCrossingMarkers(map, markerLib) {
    const dataEl = document.getElementById("crossings-data");
    const emptyEl = document.getElementById("crossing-empty");
    const detailEl = document.getElementById("crossing-detail");
    if (!dataEl || !detailEl) return;

    const crossings = JSON.parse(dataEl.textContent);
    const nameEl = detailEl.querySelector("[data-crossing-name]");
    const barrierEl = detailEl.querySelector("[data-crossing-barrier]");
    const coordsEl = detailEl.querySelector("[data-crossing-coords]");
    const osmLinkEl = detailEl.querySelector("[data-crossing-osm-link]");
    const closeBtn = document.getElementById("crossing-close");

    window.vz.crossingMarkers = new Map();
    let selectedId = null;

    function setSelected(id) {
      if (selectedId !== null) {
        const prev = window.vz.crossingMarkers.get(selectedId);
        if (prev) {
          prev.marker.zIndex = undefined;
          if (prev.pin) {
            prev.pin.background = PIN_NEUTRAL.background;
            prev.pin.borderColor = PIN_NEUTRAL.borderColor;
          }
        }
      }
      selectedId = id;
      if (id !== null) {
        const cur = window.vz.crossingMarkers.get(id);
        if (cur) {
          cur.marker.zIndex = 1000;
          if (cur.pin) {
            cur.pin.background = PIN_SELECTED.background;
            cur.pin.borderColor = PIN_SELECTED.borderColor;
          }
        }
      }
    }

    function showDetail(c) {
      if (nameEl) nameEl.textContent = c.name || "Unnamed level crossing";
      if (barrierEl) barrierEl.textContent = c.barrier || "Not mapped";
      if (coordsEl) {
        coordsEl.textContent =
          Number(c.lat).toFixed(5) + ", " + Number(c.lng).toFixed(5);
      }
      detailEl
        .querySelectorAll("[data-source-variant]")
        .forEach((el) => {
          el.hidden = el.dataset.sourceVariant !== c.source;
        });
      if (osmLinkEl) {
        if (c.source === "osm" && c.osm_type && c.osm_id) {
          osmLinkEl.href =
            "https://www.openstreetmap.org/" + c.osm_type + "/" + c.osm_id;
          osmLinkEl.hidden = false;
        } else {
          osmLinkEl.hidden = true;
        }
      }
      if (emptyEl) emptyEl.hidden = true;
      detailEl.hidden = false;
      setSelected(c.id);
      detailEl.focus();
      if (window.vz.expandSheet) window.vz.expandSheet();
    }

    function hideDetail() {
      detailEl.hidden = true;
      if (emptyEl) emptyEl.hidden = false;
      setSelected(null);
    }

    if (closeBtn) closeBtn.addEventListener("click", hideDetail);
    detailEl.addEventListener("keydown", (event) => {
      if (event.key === "Escape") hideDetail();
    });

    const useAdvanced = window.vz.hasMapId && markerLib.AdvancedMarkerElement;
    crossings.forEach((c) => {
      const position = { lat: Number(c.lat), lng: Number(c.lng) };
      const title = c.name || "Level crossing (OSM)";
      let marker;
      let pin = null;
      if (useAdvanced) {
        pin = new markerLib.PinElement({
          background: PIN_NEUTRAL.background,
          borderColor: PIN_NEUTRAL.borderColor,
          glyphColor: PIN_NEUTRAL.glyphColor,
        });
        marker = new markerLib.AdvancedMarkerElement({
          map: map,
          position: position,
          title: title,
          content: pin.element,
          gmpClickable: true,
        });
        const onSelect = () => showDetail(c);
        marker.addListener("gmp-click", onSelect);
        marker.addListener("click", onSelect);
      } else {
        marker = new markerLib.Marker({
          map: map,
          position: position,
          title: title,
        });
        marker.addListener("click", () => showDetail(c));
      }
      window.vz.crossingMarkers.set(c.id, { marker: marker, pin: pin });
    });
  }

  async function init() {
    try {
      const { Map } = await google.maps.importLibrary("maps");
      const markerLib = await google.maps.importLibrary("marker");
      const { PlaceAutocompleteElement } = await google.maps.importLibrary("places");

      const map = new Map(document.getElementById("map"), {
        center: { lat: cfg.center[0], lng: cfg.center[1] },
        zoom: cfg.zoom,
        mapId: cfg.mapId || undefined,
        gestureHandling: coarsePointer ? "greedy" : "cooperative",
        fullscreenControl: false,
        streetViewControl: false,
        mapTypeControl: false,
      });

      const tilesLoaded = map.addListener("tilesloaded", () => {
        if (loadingEl) loadingEl.hidden = true;
        tilesLoaded.remove();
      });

      window.vz.map = map;
      window.vz.AdvancedMarkerElement = markerLib.AdvancedMarkerElement;
      window.vz.reducedMotion = reducedMotion;
      window.vz.hasMapId = Boolean(cfg.mapId);
      setupAutocomplete(PlaceAutocompleteElement);
      try {
        setupCrossingMarkers(map, markerLib);
      } catch (err) {
        console.warn("Crossing markers failed to initialise:", err);
      }
    } catch (err) {
      showApiError();
    }
  }

  init();
})();
