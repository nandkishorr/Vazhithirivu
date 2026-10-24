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

  // The picker's internal text input lives in its (open) shadow root.
  // Guarded: if Google changes internals this degrades to "".
  function pickerText(picker) {
    try {
      const el =
        picker.shadowRoot && picker.shadowRoot.querySelector("input");
      return el ? el.value : "";
    } catch (err) {
      return "";
    }
  }

  function setupPlacePickers(map) {
    const fields = [
      ["origin-picker", "id_origin", "id_origin_place_id", true],
      ["destination-picker", "id_destination", "id_destination_place_id", false],
    ];
    fields.forEach(([pickerId, inputId, hiddenId, isOrigin]) => {
      const picker = document.getElementById(pickerId);
      const input = document.getElementById(inputId);
      const hidden = document.getElementById(hiddenId);
      if (!picker || !input || !hidden) return;
      if (map && picker.bindTo) picker.bindTo(map);

      picker.addEventListener("gmpx-placechange", () => {
        const place = picker.value;
        if (place && place.id) {
          const name =
            typeof place.displayName === "string"
              ? place.displayName
              : (place.displayName && place.displayName.text) || "";
          input.value = place.formattedAddress || name;
          hidden.value = place.id;
          // Picking a real place for From supersedes a "My location" fix.
          if (isOrigin) {
            const latEl = document.getElementById("id_origin_lat");
            const lngEl = document.getElementById("id_origin_lng");
            if (latEl) latEl.value = "";
            if (lngEl) lngEl.value = "";
          }
        } else {
          // Input cleared or no matching place: drop stale form values.
          input.value = "";
          hidden.value = "";
        }
      });
    });

    // gmpx-place-picker has no form name and typed-but-unselected text is
    // not a Place, so it would submit as empty. Sync the visible text on
    // submit; if it was edited after a pick, drop the stale place id.
    const form = document.getElementById("route-form");
    if (form) {
      form.addEventListener("submit", () => {
        fields.forEach(([pickerId, inputId, hiddenId]) => {
          const picker = document.getElementById(pickerId);
          const input = document.getElementById(inputId);
          const hidden = document.getElementById(hiddenId);
          if (!picker || !input || !hidden) return;
          const text = pickerText(picker);
          if (text !== input.value) {
            input.value = text;
            hidden.value = "";
          }
        });
      });
    }
  }

  // --- Crossing markers ------------------------------------------------------
  // Status colouring always pairs a colour with a glyph (non-colour cue).
  // Unknown/no-report states must never use green.
  const STATE_STYLE = {
    closed_reported: { color: "#dc2626", border: "#991b1b", glyph: "\u2715" },
    open_reported: { color: "#16a34a", border: "#166534", glyph: "\u2713" },
    conflicting: { color: "#d97706", border: "#92400e", glyph: "!" },
    stale: { color: "#94a3b8", border: "#64748b", glyph: "\u2026" },
    unknown: { color: "#64748b", border: "#475569", glyph: "?" },
  };
  const LEGACY_ICON_SCALE = 8;

  function setupCrossingMarkers(map, markerLib) {
    const emptyEl = document.getElementById("crossing-empty");
    const detailEl = document.getElementById("crossing-detail");
    const chipEl = document.getElementById("crossings-status");
    const chipTextEl = chipEl && chipEl.querySelector("[data-crossings-status-text]");
    if (!detailEl || !cfg.crossingsUrl) return;

    function setChip(text) {
      if (!chipEl) return;
      chipEl.hidden = false;
      if (chipTextEl) chipTextEl.textContent = text;
    }

    const nameEl = detailEl.querySelector("[data-crossing-name]");
    const barrierEl = detailEl.querySelector("[data-crossing-barrier]");
    const coordsEl = detailEl.querySelector("[data-crossing-coords]");
    const osmLinkEl = detailEl.querySelector("[data-crossing-osm-link]");
    const detailLinkEl = detailEl.querySelector("[data-crossing-detail-link]");
    const summaryEl = detailEl.querySelector("[data-status-summary]");
    const errorEl = detailEl.querySelector("[data-status-error]");
    const closeBtn = document.getElementById("crossing-close");
    const statusUrlTemplate = detailEl.dataset.statusUrlTemplate;
    const detailUrlTemplate = detailEl.dataset.detailUrlTemplate;

    window.vz.crossingMarkers = new Map();
    let selectedId = null;
    let statusTimer = null;
    let statusFetch = null;

    const KNOWN_STATES = [
      "closed_reported",
      "open_reported",
      "conflicting",
      "stale",
      "unknown",
    ];

    function urlFor(template, id) {
      return template.replace(/\/0\/$/, "/" + encodeURIComponent(id) + "/");
    }

    function showStatusVariant(state) {
      detailEl
        .querySelectorAll("[data-status-variant]")
        .forEach((el) => {
          el.hidden = el.dataset.statusVariant !== state;
        });
    }

    function reportAge(seconds) {
      if (seconds === null || seconds === undefined) return "";
      if (seconds < 60) return "just now";
      if (seconds < 3600) return Math.round(seconds / 60) + " min ago";
      return Math.round(seconds / 3600) + " h ago";
    }

    function pluralizeSay(n) {
      return n === 1 ? "says" : "say";
    }

    function statusSummary(payload) {
      const status = payload.status || {};
      const policy = payload.policy || {};
      const age = reportAge(status.last_report_age_seconds);
      switch (status.state) {
        case "unknown":
          return (
            "No community reports in the last " +
            policy.stale_minutes +
            " minutes."
          );
        case "stale":
          return (
            "Last report (" +
            status.last_reported_state +
            ") " +
            age +
            " — too old to rely on."
          );
        case "closed_reported":
        case "open_reported": {
          const n = status.supporting_reports || 0;
          return (
            "Last report " +
            age +
            " · based on " +
            n +
            " community report" +
            (n === 1 ? "" : "s") +
            "."
          );
        }
        case "conflicting": {
          const support = status.supporting_reports || 0;
          const oppose = status.opposing_reports || 0;
          const other =
            status.last_reported_state === "closed" ? "open" : "closed";
          return (
            support +
            " " +
            pluralizeSay(support) +
            " " +
            status.last_reported_state +
            ", " +
            oppose +
            " " +
            pluralizeSay(oppose) +
            " " +
            other +
            " in the last few minutes."
          );
        }
        default:
          return "";
      }
    }

    function renderStatus(payload) {
      const status = payload.status || {};
      const state = KNOWN_STATES.includes(status.state)
        ? status.state
        : "unknown";
      showStatusVariant(state);
      if (summaryEl) summaryEl.textContent = statusSummary(payload);
    }

    function statusFailed() {
      showStatusVariant("unknown");
      if (summaryEl) summaryEl.textContent = "";
      if (errorEl) errorEl.hidden = false;
    }

    function stopStatusRefresh() {
      if (statusTimer !== null) {
        clearInterval(statusTimer);
        statusTimer = null;
      }
      if (statusFetch) {
        statusFetch.abort();
        statusFetch = null;
      }
    }

    function loadStatus(id) {
      if (!statusUrlTemplate) return;
      if (statusFetch) statusFetch.abort();
      const controller = new AbortController();
      statusFetch = controller;
      fetch(urlFor(statusUrlTemplate, id), {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
        signal: controller.signal,
      })
        .then((response) => {
          if (!response.ok) throw new Error("status " + response.status);
          return response.json();
        })
        .then((payload) => {
          if (selectedId !== id || controller.signal.aborted) return;
          renderStatus(payload);
          const state = KNOWN_STATES.includes(payload.status && payload.status.state)
            ? payload.status.state
            : "unknown";
          const entry = window.vz.crossingMarkers.get(id);
          if (entry && entry.state !== state) {
            entry.state = state;
            if (entry.data) entry.data.status = payload.status;
            applyMarkerVisual(entry);
          }
        })
        .catch((err) => {
          if (err && err.name === "AbortError") return;
          if (selectedId !== id) return;
          statusFailed();
        });
    }

    function startStatusRefresh(id) {
      stopStatusRefresh();
      statusTimer = setInterval(() => {
        if (document.hidden || selectedId !== id) return;
        loadStatus(id);
      }, 60000);
    }

    function markerTitle(c) {
      const label = (c.status && c.status.label) || "Status unknown";
      return (
        (c.name || "Level crossing") +
        " \u2014 " +
        label +
        " (community reports, not official)"
      );
    }

    function applyMarkerVisual(entry) {
      const style = STATE_STYLE[entry.state] || STATE_STYLE.unknown;
      const selected = entry.id === selectedId;
      const title = markerTitle(entry.data || {});
      if (entry.pin) {
        entry.pin.background = style.color;
        entry.pin.borderColor = style.border;
        entry.pin.glyph = style.glyph;
        entry.pin.glyphColor = "#fff";
        entry.pin.scale = selected ? 1.3 : 1;
        entry.marker.title = title;
        entry.marker.zIndex = selected ? 1000 : undefined;
      } else {
        entry.marker.setIcon({
          path: google.maps.SymbolPath.CIRCLE,
          scale: selected ? LEGACY_ICON_SCALE * 1.3 : LEGACY_ICON_SCALE,
          fillColor: style.color,
          fillOpacity: 1,
          strokeColor: "#fff",
          strokeWeight: 2,
        });
        entry.marker.setLabel({
          text: style.glyph,
          color: "#fff",
          fontSize: "11px",
        });
        entry.marker.setTitle(title);
        entry.marker.setZIndex(selected ? 1000 : undefined);
      }
    }

    function setSelected(id) {
      if (selectedId !== null && selectedId !== id) {
        const prev = window.vz.crossingMarkers.get(selectedId);
        if (prev) applyMarkerVisual(prev);
      }
      selectedId = id;
      if (id !== null) {
        const cur = window.vz.crossingMarkers.get(id);
        if (cur) applyMarkerVisual(cur);
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
      if (detailLinkEl && detailUrlTemplate) {
        detailLinkEl.href = urlFor(detailUrlTemplate, c.id);
      }
      const knownState = c.status && KNOWN_STATES.includes(c.status.state)
        ? c.status.state
        : "unknown";
      showStatusVariant(knownState);
      if (summaryEl) {
        summaryEl.textContent = "Checking recent community reports…";
      }
      if (errorEl) errorEl.hidden = true;
      if (emptyEl) emptyEl.hidden = true;
      detailEl.hidden = false;
      setSelected(c.id);
      startStatusRefresh(c.id);
      loadStatus(c.id);
      detailEl.focus();
      if (window.vz.expandSheet) window.vz.expandSheet();
    }

    function hideDetail() {
      detailEl.hidden = true;
      if (emptyEl) emptyEl.hidden = false;
      setSelected(null);
      stopStatusRefresh();
    }

    if (closeBtn) closeBtn.addEventListener("click", hideDetail);
    detailEl.addEventListener("keydown", (event) => {
      if (event.key === "Escape") hideDetail();
    });

    const useAdvanced = window.vz.hasMapId && markerLib.AdvancedMarkerElement;

    function normalizeState(state) {
      return KNOWN_STATES.includes(state) ? state : "unknown";
    }

    function createMarker(c) {
      const position = { lat: Number(c.lat), lng: Number(c.lng) };
      const entry = {
        id: c.id,
        marker: null,
        pin: null,
        data: c,
        state: normalizeState(c.status && c.status.state),
      };
      const onSelect = () => {
        const current = window.vz.crossingMarkers.get(c.id);
        showDetail(current ? current.data : c);
      };
      if (useAdvanced) {
        const style = STATE_STYLE[entry.state];
        entry.pin = new markerLib.PinElement({
          background: style.color,
          borderColor: style.border,
          glyphColor: "#fff",
          glyph: style.glyph,
        });
        entry.marker = new markerLib.AdvancedMarkerElement({
          map: map,
          position: position,
          title: markerTitle(c),
          content: entry.pin.element,
          gmpClickable: true,
        });
        entry.marker.addListener("gmp-click", onSelect);
      } else {
        entry.marker = new markerLib.Marker({ map: map, position: position });
        entry.marker.addListener("click", onSelect);
      }
      applyMarkerVisual(entry);
      return entry;
    }

    // AdvancedMarkerElement uses the `map` property; legacy Marker needs setMap().
    function setMarkerMap(entry, target) {
      if (entry.pin) {
        if (entry.marker.map !== target) entry.marker.map = target;
      } else if (entry.marker.getMap() !== target) {
        entry.marker.setMap(target);
      }
    }

    function applyCrossings(list) {
      const seen = new Set();
      list.forEach((c) => {
        seen.add(c.id);
        const state = normalizeState(c.status && c.status.state);
        const entry = window.vz.crossingMarkers.get(c.id);
        if (entry) {
          const changed = entry.state !== state;
          entry.data = c;
          entry.state = state;
          setMarkerMap(entry, map);
          if (changed) applyMarkerVisual(entry);
        } else {
          window.vz.crossingMarkers.set(c.id, createMarker(c));
        }
      });
      // Remove markers no longer in view — except the selected one.
      window.vz.crossingMarkers.forEach((entry, id) => {
        if (!seen.has(id) && id !== selectedId) {
          setMarkerMap(entry, null);
          window.vz.crossingMarkers.delete(id);
        }
      });
    }

    function removeAllExceptSelected() {
      window.vz.crossingMarkers.forEach((entry, id) => {
        if (id !== selectedId) {
          setMarkerMap(entry, null);
          window.vz.crossingMarkers.delete(id);
        }
      });
    }

    // --- Bbox loading (idle + debounce, no polling) --------------------------
    let fetchCtl = null;
    let fetchSeq = 0;
    let lastBBox = null;
    let lastFetchedAt = 0;
    let idleTimer = null;

    function spanDeg(b) {
      return Math.max(b.e - b.w, b.n - b.s);
    }

    function viewBBox() {
      const bounds = map.getBounds();
      if (!bounds) return null;
      const sw = bounds.getSouthWest();
      const ne = bounds.getNorthEast();
      return { w: sw.lng(), s: sw.lat(), e: ne.lng(), n: ne.lat() };
    }

    function clampOut(b) {
      return {
        w: Math.max(-180, Math.floor(b.w * 1000) / 1000),
        s: Math.max(-90, Math.floor(b.s * 1000) / 1000),
        e: Math.min(180, Math.ceil(b.e * 1000) / 1000),
        n: Math.min(90, Math.ceil(b.n * 1000) / 1000),
      };
    }

    function fetchBox() {
      const view = viewBBox();
      if (!view) return null;
      const padLng = (view.e - view.w) * 0.2;
      const padLat = (view.n - view.s) * 0.2;
      let box = clampOut({
        w: view.w - padLng,
        s: view.s - padLat,
        e: view.e + padLng,
        n: view.n + padLat,
      });
      if (spanDeg(box) > cfg.bboxMaxSpan) box = clampOut(view);
      if (spanDeg(box) > cfg.bboxMaxSpan) return false;
      return box;
    }

    function doFetch(box) {
      if (fetchCtl) fetchCtl.abort();
      const ctl = new AbortController();
      fetchCtl = ctl;
      const seq = ++fetchSeq;
      setChip("Loading crossings\u2026");
      fetch(cfg.crossingsUrl + "?bbox=" + [box.w, box.s, box.e, box.n].join(","), {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
        signal: ctl.signal,
      })
        .then((response) =>
          response.json().then((body) => ({ ok: response.ok, status: response.status, body: body }))
        )
        .then((result) => {
          if (ctl.signal.aborted || seq !== fetchSeq) return;
          if (!result.ok) {
            if (result.status === 400 && result.body && result.body.error === "bbox_too_large") {
              setChip("Zoom in to see railway crossings");
            } else {
              setChip("Couldn't load crossings. Move the map to retry.");
            }
            return;
          }
          const body = result.body;
          lastBBox = box;
          lastFetchedAt = Date.now();
          const list = body.crossings || [];
          applyCrossings(list);
          const n = body.count != null ? body.count : list.length;
          if (body.truncated) {
            setChip("Showing the first " + n + " crossings \u2014 zoom in to see all");
          } else if (n === 0) {
            setChip("No mapped crossings in this area");
          } else {
            setChip(n + " crossing" + (n === 1 ? "" : "s") + " \u00b7 community status, not official");
          }
        })
        .catch((err) => {
          if (err && err.name === "AbortError") return;
          if (seq !== fetchSeq) return;
          setChip("Couldn't load crossings. Move the map to retry.");
        });
    }

    function requestLoad() {
      if (map.getZoom() < cfg.crossingsMinZoom) {
        if (fetchCtl) fetchCtl.abort();
        fetchSeq += 1;
        removeAllExceptSelected();
        lastBBox = null;
        setChip("Zoom in to see railway crossings");
        return;
      }
      const view = viewBBox();
      if (!view) return;
      const box = fetchBox();
      if (box === null) return;
      if (box === false) {
        if (fetchCtl) fetchCtl.abort();
        fetchSeq += 1;
        setChip("Zoom in to see railway crossings");
        return;
      }
      // The current view is already covered by a fresh fetch — skip it.
      if (
        lastBBox &&
        Date.now() - lastFetchedAt < 60000 &&
        view.w >= lastBBox.w &&
        view.s >= lastBBox.s &&
        view.e <= lastBBox.e &&
        view.n <= lastBBox.n
      ) {
        return;
      }
      doFetch(box);
    }

    map.addListener("idle", () => {
      if (idleTimer) clearTimeout(idleTimer);
      idleTimer = setTimeout(requestLoad, 300);
    });
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden && Date.now() - lastFetchedAt > 60000) {
        requestLoad();
      }
    });
  }


  // --- Route display -------------------------------------------------------
  // Route geometry comes from #route-data (server-rendered). Only the
  // selected route is emphasised; switching is always user-confirmed.
  function setupRoutes(map, markerLib) {
    const dataEl = document.getElementById("route-data");
    const announceEl = document.getElementById("route-announce");
    if (!dataEl) return;
    let data;
    try {
      data = JSON.parse(dataEl.textContent);
    } catch (err) {
      return;
    }
    if (!data || !Array.isArray(data.routes) || data.routes.length === 0) return;

    const blockingNames = (data.blocking || []).join(", ");
    const selectedColor = "#1d4ed8"; // brand
    const altColor = "#64748b"; // slate — never green for "avoids"

    const polylines = new Map();
    const selectedIdRef = { id: "r0" };

    function lineBounds(coords) {
      const bounds = new google.maps.LatLngBounds();
      coords.forEach(([lat, lng]) => bounds.extend({ lat: lat, lng: lng }));
      return bounds;
    }

    function styleFor(id, selected) {
      if (selected) {
        return { strokeColor: selectedColor, strokeOpacity: 0.9, strokeWeight: 6, icons: undefined, zIndex: 100 };
      }
      return {
        strokeColor: altColor, strokeOpacity: 0, strokeWeight: 4,
        icons: [{
          icon: { path: "M 0,-1 0,1", strokeOpacity: 0.9, strokeWeight: 4, strokeColor: altColor, scale: 3 },
          offset: "0", repeat: "14px",
        }],
        zIndex: 10,
      };
    }

    data.routes.forEach((route) => {
      if (!route.coords || route.coords.length < 2) return;
      const path = route.coords.map(([lat, lng]) => ({ lat: lat, lng: lng }));
      const line = new google.maps.Polyline(
        Object.assign(
          {
            map: map,
            path: path,
            clickable: true,
          },
          styleFor(route.id, route.id === selectedIdRef.id)
        )
      );
      line.addListener("click", () => {
        if (route.id !== selectedIdRef.id) selectRoute(route.id, true);
      });
      polylines.set(route.id, { line: line, path: path, route: route });
    });

    // Markers for closed/conflicting crossings on the displayed routes.
    const useAdvanced = window.vz.hasMapId && markerLib.AdvancedMarkerElement;
    const seen = new Set();
    data.routes.forEach((route) => {
      (route.crossings || []).forEach((c) => {
        if (seen.has(c.id)) return;
        seen.add(c.id);
        if (c.state !== "closed_reported" && c.state !== "conflicting") return;
        const style = STATE_STYLE[c.state] || STATE_STYLE.unknown;
        const position = { lat: Number(c.lat), lng: Number(c.lng) };
        const title =
          (c.name || "Level crossing") +
          " \u2014 " +
          (c.state === "closed_reported" ? "Reported closed" : "Conflicting reports") +
          " (community reports, not official)";
        if (useAdvanced) {
          const pin = new markerLib.PinElement({
            background: style.color,
            borderColor: style.border,
            glyphColor: "#fff",
            glyph: style.glyph,
            scale: 0.8,
          });
          new markerLib.AdvancedMarkerElement({
            map: map,
            position: position,
            title: title,
            content: pin.element,
          });
        } else {
          new google.maps.Marker({
            map: map,
            position: position,
            title: title,
            icon: {
              path: google.maps.SymbolPath.CIRCLE,
              scale: LEGACY_ICON_SCALE * 0.8,
              fillColor: style.color,
              fillOpacity: 1,
              strokeColor: "#fff",
              strokeWeight: 2,
            },
            label: { text: style.glyph, color: "#fff", fontSize: "10px" },
          });
        }
      });
    });

    function fitTo(id) {
      const entry = polylines.get(id);
      if (!entry) return;
      map.fitBounds(lineBounds(entry.route.coords), 60);
    }

    function showPanel(id) {
      document.querySelectorAll("[data-route-panel]").forEach((panel) => {
        panel.hidden = panel.dataset.routePanel !== id;
      });
    }

    function selectRoute(id, fromMapClick) {
      if (!polylines.has(id)) return;
      const prev = selectedIdRef.id;
      selectedIdRef.id = id;
      polylines.forEach((entry, routeId) => {
        entry.line.setOptions(styleFor(routeId, routeId === id));
      });
      document.querySelectorAll("[data-route-option]").forEach((btn) => {
        const selected = btn.dataset.routeOption === id;
        btn.setAttribute("aria-pressed", selected ? "true" : "false");
        if (selected) {
          btn.setAttribute("data-selected", "");
        } else {
          btn.removeAttribute("data-selected");
        }
      });
      showPanel(id);
      fitTo(id);
      if (announceEl) {
        const route = data.routes.find((r) => r.id === id);
        if (id === "r0" && prev !== "r0") {
          announceEl.textContent = "Back to the original route.";
        } else if (route && route.verification === "verified") {
          announceEl.textContent =
            "Switched to the alternative route. It avoids " +
            blockingNames +
            " (checked against route geometry).";
        } else if (route && route.verification === "passes") {
          announceEl.textContent =
            "Showing a route that also passes a reported-closed crossing.";
        } else if (blockingNames) {
          announceEl.textContent =
            "Showing an alternative that is not verified to avoid " +
            blockingNames +
            ".";
        } else {
          announceEl.textContent = "Switched route.";
        }
      }
    }

    document.querySelectorAll("[data-route-select]").forEach((btn) => {
      btn.addEventListener("click", () => selectRoute(btn.dataset.routeSelect, false));
    });

    fitTo(selectedIdRef.id);
  }

  async function init() {
    try {
      const { Map, Circle } = await google.maps.importLibrary("maps");
      const markerLib = await google.maps.importLibrary("marker");
      // Places is loaded lazily by the gmpx-place-picker components.

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
      window.vz.Circle = Circle;
      window.vz.crossingsMinZoom = cfg.crossingsMinZoom;
      try {
        setupPlacePickers(map);
      } catch (err) {
        console.warn("Place pickers failed to initialise:", err);
      }
      try {
        setupCrossingMarkers(map, markerLib);
      } catch (err) {
        console.warn("Crossing markers failed to initialise:", err);
      }
      try {
        setupRoutes(map, markerLib);
      } catch (err) {
        console.warn("Route display failed to initialise:", err);
      }
    } catch (err) {
      showApiError();
    }
  }

  init();
})();
