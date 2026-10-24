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
    // Simulated states are violet (demo data) and always labelled.
    closed_simulated: { color: "#7c3aed", border: "#5b21b6", glyph: "\u2715" },
    open_simulated: { color: "#7c3aed", border: "#5b21b6", glyph: "\u2713" },
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
    let selectedStatusAsOf = null;
    let statusTimer = null;
    let statusFetch = null;

    const KNOWN_STATES = [
      "closed_reported",
      "open_reported",
      "conflicting",
      "stale",
      "unknown",
      "closed_simulated",
      "open_simulated",
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
        case "closed_simulated":
          return (
            "Simulated gate closure (demo) — not a real-world report." +
            (payload.simulation && payload.simulation.label
              ? " Run: " + payload.simulation.label + "."
              : "")
          );
        case "open_simulated":
          return "Simulated open gate (demo) — not a real-world report.";
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
          if (payload.as_of) selectedStatusAsOf = payload.as_of;
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
      const suffix =
        c.status && c.status.simulated
          ? " (simulation demo, not real-world status)"
          : " (community reports, not official)";
      return (
        (c.name || "Level crossing") + " \u2014 " + label + suffix
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
      scheduleResubscribe();
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
      selectedStatusAsOf = null;
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

    // "Route here" on the detail card: the selected crossing becomes the
    // destination and the route re-plans from the current origin.
    const routeHereBtn = document.getElementById("crossing-route-here");
    if (routeHereBtn) {
      routeHereBtn.addEventListener("click", () => {
        const entry =
          selectedId !== null
            ? window.vz.crossingMarkers.get(selectedId)
            : null;
        const c = entry ? entry.data : null;
        if (!c || !window.vz.rerouteToDestination) return;
        window.vz.rerouteToDestination({
          text: c.name || "Level crossing",
          lat: Number(c.lat),
          lng: Number(c.lng),
        });
      });
    }

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

    function applyCrossings(list, asOf) {
      const seen = new Set();
      list.forEach((c) => {
        seen.add(c.id);
        const state = normalizeState(c.status && c.status.state);
        const entry = window.vz.crossingMarkers.get(c.id);
        if (entry) {
          const changed = entry.state !== state;
          entry.data = c;
          entry.state = state;
          if (asOf) entry.statusAsOf = asOf;
          setMarkerMap(entry, map);
          if (changed) applyMarkerVisual(entry);
        } else {
          const created = createMarker(c);
          created.statusAsOf = asOf || null;
          window.vz.crossingMarkers.set(c.id, created);
        }
      });
      // Remove markers no longer in view — except the selected one.
      window.vz.crossingMarkers.forEach((entry, id) => {
        if (!seen.has(id) && id !== selectedId) {
          setMarkerMap(entry, null);
          window.vz.crossingMarkers.delete(id);
        }
      });
      scheduleResubscribe();
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
          applyCrossings(list, body.as_of);
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

    function requestLoad(force) {
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
        !force &&
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

    // Refresh statuses periodically while the page is visible. This is
    // both the WebSocket fallback and the only way time-based ageing
    // (fresh -> stale -> unknown) reaches the client — a report expiring
    // produces no push. requestLoad() skips fresh/covered views, so this
    // costs at most one small fetch per minute per tab.
    setInterval(() => {
      if (!document.hidden) requestLoad();
    }, 60000);

    // --- Realtime pushes (ADR-014) -----------------------------------------
    // Subscriptions follow the marker set plus the selected crossing.
    // Messages carry the same server-derived status payload as the HTTP
    // API; reconnects resubscribe and receive a fresh snapshot.
    const rt = { ws: null, attempts: 0, resubTimer: null, retryTimer: null };

    function subscribedIds() {
      const ids = Array.from(window.vz.crossingMarkers.keys());
      if (selectedId !== null && !ids.includes(selectedId)) ids.push(selectedId);
      return ids;
    }

    function sendSubscribe() {
      if (rt.ws && rt.ws.readyState === WebSocket.OPEN) {
        rt.ws.send(JSON.stringify({ type: "subscribe", crossing_ids: subscribedIds() }));
      }
    }

    function scheduleResubscribe() {
      if (rt.resubTimer !== null) return;
      // Debounce above the server's per-connection subscribe minimum so
      // pan-driven resubscribes don't hit the rate limit.
      rt.resubTimer = setTimeout(() => {
        rt.resubTimer = null;
        sendSubscribe();
      }, 1100);
    }

    function applyPushedStatus(id, status, policy, asOf) {
      if (!Number.isInteger(id)) return;
      const entry = window.vz.crossingMarkers.get(id);
      if (entry) {
        // Ignore out-of-order frames older than what we already applied.
        if (asOf && entry.statusAsOf && asOf < entry.statusAsOf) return;
        if (asOf) entry.statusAsOf = asOf;
        const state = normalizeState(status && status.state);
        if (entry.data) entry.data.status = status;
        if (entry.state !== state) {
          entry.state = state;
          applyMarkerVisual(entry);
        }
      }
      if (
        id === selectedId &&
        status &&
        !(asOf && selectedStatusAsOf && asOf < selectedStatusAsOf)
      ) {
        if (asOf) selectedStatusAsOf = asOf;
        renderStatus({ status: status, policy: policy || {} });
      }
    }

    function handleRealtimeMessage(event) {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch (err) {
        return;
      }
      if (!msg || typeof msg !== "object") return;
      if (msg.type === "status.snapshot" && msg.statuses) {
        Object.keys(msg.statuses).forEach((key) => {
          applyPushedStatus(Number(key), msg.statuses[key], msg.policy, msg.as_of);
        });
      } else if (msg.type === "crossing.status") {
        applyPushedStatus(Number(msg.crossing_id), msg.status, msg.policy, msg.as_of);
      } else if (msg.type === "error" && msg.code === "rate_limited") {
        const waitMs = Math.max(200, Math.ceil((msg.retry_after_seconds || 1) * 1000));
        if (rt.resubTimer) clearTimeout(rt.resubTimer);
        rt.resubTimer = setTimeout(() => {
          rt.resubTimer = null;
          sendSubscribe();
        }, waitMs);
      }
    }

    function connectRealtime() {
      if (!cfg.crossingsWsUrl || rt.attempts >= 10) return;
      let ws;
      try {
        ws = new WebSocket(cfg.crossingsWsUrl);
      } catch (err) {
        rt.attempts = 10;
        return;
      }
      rt.ws = ws;
      ws.onopen = () => {
        rt.attempts = 0;
        sendSubscribe();
      };
      ws.onmessage = handleRealtimeMessage;
      ws.onerror = () => {
        try {
          ws.close();
        } catch (err) {
          /* closing an errored socket must not throw */
        }
      };
      ws.onclose = () => {
        if (rt.ws !== ws) return;
        rt.ws = null;
        rt.attempts += 1;
        if (rt.attempts >= 10) return;
        const delay =
          Math.min(30000, 1000 * Math.pow(2, rt.attempts)) +
          Math.floor(Math.random() * 500);
        rt.retryTimer = setTimeout(connectRealtime, delay);
      };
    }

    window.addEventListener("online", () => {
      if (!rt.ws || rt.ws.readyState !== WebSocket.OPEN) {
        rt.attempts = 0;
        connectRealtime();
      }
    });

    // Let the simulation layer recolour pins on gate ticks and force a
    // status refetch when a run ends.
    window.vz.applyPushedStatus = applyPushedStatus;
    window.vz.requestCrossingLoad = requestLoad;

    connectRealtime();
  }


  // --- Route display + dynamic rerouting (ADR-016) ------------------------
  // Route geometry comes from #route-data (server-rendered) or a
  // ?format=json fetch. Only the selected route is emphasised; switching
  // is always user-confirmed. Clicking a place or any point on the map
  // sets it as the destination and re-plans without a page reload.
  const MY_LOCATION_TEXT = "My location";

  function setupRoutes(map, markerLib) {
    const dataEl = document.getElementById("route-data");
    const resultEl = document.getElementById("route-result");
    const liveEl = document.getElementById("route-live");

    const selectedColor = "#1d4ed8"; // brand
    const altColor = "#64748b"; // slate — never green for "avoids"
    const casingColor = "#ffffff";

    const polylines = new Map();
    let endpointMarkers = [];
    let routeMarkers = [];
    let currentData = null;
    let blockingNames = "";
    let selectedId = "r0";
    let rerouteCtl = null;

    function announce(text) {
      if (liveEl) liveEl.textContent = text;
    }

    function removeOverlay(entry) {
      if (entry.advanced) entry.ref.map = null;
      else entry.ref.setMap(null);
    }

    function clearLayers() {
      polylines.forEach((entry) => {
        entry.line.setMap(null);
        entry.casing.setMap(null);
      });
      polylines.clear();
      endpointMarkers.forEach(removeOverlay);
      endpointMarkers = [];
      routeMarkers.forEach(removeOverlay);
      routeMarkers = [];
    }

    function lineBounds(coords) {
      const bounds = new google.maps.LatLngBounds();
      coords.forEach(([lat, lng]) => bounds.extend({ lat: lat, lng: lng }));
      return bounds;
    }

    // Selected route: bold solid line over a white casing so it stays
    // readable over any basemap. Alternates stay dashed slate.
    function styleFor(id, selected) {
      if (selected) {
        return {
          strokeColor: selectedColor,
          strokeOpacity: 1,
          strokeWeight: 8,
          icons: undefined,
          zIndex: 100,
        };
      }
      return {
        strokeColor: altColor,
        strokeOpacity: 0,
        strokeWeight: 5,
        icons: [
          {
            icon: {
              path: "M 0,-1 0,1",
              strokeOpacity: 0.95,
              strokeWeight: 5,
              strokeColor: altColor,
              scale: 3,
            },
            offset: "0",
            repeat: "14px",
          },
        ],
        zIndex: 10,
      };
    }

    const useAdvanced = window.vz.hasMapId && markerLib.AdvancedMarkerElement;

    // A/B pins at the selected route's endpoints.
    function addEndpointMarkers() {
      const primary =
        currentData.routes.find((r) => r.id === selectedId) ||
        currentData.routes[0];
      if (!primary || !primary.coords || primary.coords.length < 2) return;
      const mk = (pos, letter, color, title) => {
        const position = { lat: pos[0], lng: pos[1] };
        if (useAdvanced) {
          const pin = new markerLib.PinElement({
            background: color,
            borderColor: color,
            glyphColor: "#fff",
            glyph: letter,
            scale: 1.15,
          });
          return {
            advanced: true,
            ref: new markerLib.AdvancedMarkerElement({
              map: map,
              position: position,
              title: title,
              content: pin.element,
              zIndex: 200,
            }),
          };
        }
        return {
          advanced: false,
          ref: new google.maps.Marker({
            map: map,
            position: position,
            title: title,
            zIndex: 200,
            icon: {
              path: google.maps.SymbolPath.CIRCLE,
              scale: 11,
              fillColor: color,
              fillOpacity: 1,
              strokeColor: "#fff",
              strokeWeight: 2,
            },
            label: {
              text: letter,
              color: "#fff",
              fontSize: "11px",
              fontWeight: "bold",
            },
          }),
        };
      };
      const start = primary.coords[0];
      const end = primary.coords[primary.coords.length - 1];
      endpointMarkers.push(mk(start, "A", selectedColor, "Start of the route"));
      endpointMarkers.push(mk(end, "B", "#dc2626", "Destination"));
    }

    // Markers for closed/conflicting crossings on the displayed routes.
    function addRouteCrossingMarkers() {
      const seen = new Set();
      currentData.routes.forEach((route) => {
        (route.crossings || []).forEach((c) => {
          if (seen.has(c.id)) return;
          seen.add(c.id);
          const ROUTE_STATE_LABEL = {
            closed_reported: "Reported closed",
            conflicting: "Conflicting reports",
            closed_simulated: "Simulated closed",
          };
          if (!(c.state in ROUTE_STATE_LABEL)) return;
          const style = STATE_STYLE[c.state] || STATE_STYLE.unknown;
          const position = { lat: Number(c.lat), lng: Number(c.lng) };
          const title =
            (c.name || "Level crossing") +
            " \u2014 " +
            ROUTE_STATE_LABEL[c.state] +
            (c.simulated
              ? " (simulation demo, not real-world status)"
              : " (community reports, not official)");
          if (useAdvanced) {
            const pin = new markerLib.PinElement({
              background: style.color,
              borderColor: style.border,
              glyphColor: "#fff",
              glyph: style.glyph,
              scale: 0.8,
            });
            routeMarkers.push({
              advanced: true,
              ref: new markerLib.AdvancedMarkerElement({
                map: map,
                position: position,
                title: title,
                content: pin.element,
              }),
            });
          } else {
            routeMarkers.push({
              advanced: false,
              ref: new google.maps.Marker({
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
              }),
            });
          }
        });
      });
    }

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

    function selectRoute(id) {
      if (!polylines.has(id)) return;
      const prev = selectedId;
      selectedId = id;
      polylines.forEach((entry, routeId) => {
        entry.line.setOptions(styleFor(routeId, routeId === id));
        entry.casing.setOptions({ visible: routeId === id });
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
      const route = currentData.routes.find((r) => r.id === id);
      if (id === "r0" && prev !== "r0") {
        announce("Back to the original route.");
      } else if (route && route.verification === "verified") {
        announce(
          "Switched to the alternative route. It avoids " +
            blockingNames +
            " (checked against route geometry)."
        );
      } else if (route && route.verification === "passes") {
        announce(
          "Showing a route that also passes a reported-closed crossing."
        );
      } else if (blockingNames) {
        announce(
          "Showing an alternative that is not verified to avoid " +
            blockingNames +
            "."
        );
      } else {
        announce("Switched route.");
      }
    }

    function applyRouteData(data) {
      clearLayers();
      currentData =
        data && Array.isArray(data.routes) && data.routes.length
          ? data
          : null;
      selectedId = "r0";
      if (!currentData) return;
      blockingNames = (currentData.blocking || []).join(", ");

      currentData.routes.forEach((route) => {
        if (!route.coords || route.coords.length < 2) return;
        const path = route.coords.map(([lat, lng]) => ({
          lat: lat,
          lng: lng,
        }));
        const isSelected = route.id === selectedId;
        const casing = new google.maps.Polyline({
          map: map,
          path: path,
          clickable: false,
          strokeColor: casingColor,
          strokeOpacity: 0.85,
          strokeWeight: 12,
          zIndex: 90,
          visible: isSelected,
        });
        const line = new google.maps.Polyline(
          Object.assign(
            { map: map, path: path, clickable: true },
            styleFor(route.id, isSelected)
          )
        );
        line.addListener("click", () => {
          if (route.id !== selectedId) selectRoute(route.id);
        });
        polylines.set(route.id, {
          line: line,
          casing: casing,
          path: path,
          route: route,
        });
      });

      addEndpointMarkers();
      addRouteCrossingMarkers();
      fitTo(selectedId);
    }

    // --- Dynamic reroute ---------------------------------------------------
    function fieldValue(id) {
      const el = document.getElementById(id);
      return el ? el.value : "";
    }

    function setField(id, value) {
      const el = document.getElementById(id);
      if (el) el.value = value == null ? "" : String(value);
    }

    function originText() {
      const picker = document.getElementById("origin-picker");
      const text = pickerText(picker);
      if (text) return text;
      return fieldValue("id_origin");
    }

    function setDestination(text, placeId, lat, lng) {
      setField("id_destination", text);
      setField("id_destination_place_id", placeId);
      setField("id_destination_lat", lat);
      setField("id_destination_lng", lng);
      const picker = document.getElementById("destination-picker");
      const input =
        picker &&
        picker.shadowRoot &&
        picker.shadowRoot.querySelector("input");
      if (input) input.value = text || "";
    }

    // Resolve the origin first: a picked place or typed address wins;
    // "My location" (the default) or an empty From means "start from my
    // position" and needs a browser fix — request it, then continue.
    function ensureOriginThen(next) {
      const placeId = fieldValue("id_origin_place_id").trim();
      const text = originText().trim();
      if (placeId || (text && text !== MY_LOCATION_TEXT)) {
        next();
        return;
      }
      const loc = window.vz.getMyLocation && window.vz.getMyLocation();
      if (loc) {
        next();
        return;
      }
      if (window.vz.requestMyLocation) {
        window.vz.requestMyLocation((pos) => {
          if (pos) next();
          // failures already surface in the location alert
        });
      } else {
        // No location helper — let the server render the honest state.
        next();
      }
    }

    function reroute() {
      const params = new URLSearchParams();
      [
        "origin",
        "origin_place_id",
        "origin_lat",
        "origin_lng",
        "destination",
        "destination_place_id",
        "destination_lat",
        "destination_lng",
      ].forEach((name) => {
        const value = fieldValue("id_" + name);
        if (value) params.set(name, value);
      });
      const url = "/?" + params.toString();
      if (rerouteCtl) rerouteCtl.abort();
      const ctl = new AbortController();
      rerouteCtl = ctl;
      if (resultEl) {
        resultEl.setAttribute("aria-busy", "true");
        resultEl.classList.add("opacity-60");
      }
      announce("Updating route\u2026");
      fetch(url + "&format=json", {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
        signal: ctl.signal,
      })
        .then((response) => {
          if (!response.ok) throw new Error("route " + response.status);
          return response.json();
        })
        .then((body) => {
          if (ctl.signal.aborted) return;
          try {
            history.pushState({}, "", url);
          } catch (err) {
            /* keeping the URL in sync is best-effort */
          }
          if (resultEl) resultEl.innerHTML = body.html || "";
          applyRouteData(body.route_data);
          if (window.vz.expandSheet) window.vz.expandSheet();
          const primary =
            body.route_data &&
            body.route_data.routes &&
            body.route_data.routes[0];
          announce(
            "Route updated" +
              (primary && primary.duration_min
                ? " \u2014 about " + primary.duration_min + " min."
                : ".")
          );
        })
        .catch((err) => {
          if (err && err.name === "AbortError") return;
          // Fall back to a full page load; the server renders the errors.
          window.location.assign(url);
        })
        .finally(() => {
          if (resultEl) {
            resultEl.removeAttribute("aria-busy");
            resultEl.classList.remove("opacity-60");
          }
        });
    }

    function goToDestination(dest) {
      setDestination(dest.text, dest.placeId || "", dest.lat, dest.lng);
      ensureOriginThen(reroute);
    }
    window.vz.rerouteToDestination = goToDestination;
    window.vz.reroute = function () {
      ensureOriginThen(reroute);
    };

    function pinnedText(lat, lng) {
      return "Pinned location (" + lat.toFixed(5) + ", " + lng.toFixed(5) + ")";
    }

    // Resolve a clicked point to something Google Maps can select — a real
    // place/address via the Geocoder. POI clicks keep their placeId; bare
    // clicks adopt the nearest result's place_id. Falls back to pinned
    // coordinates when geocoding is unavailable or returns nothing.
    function resolveDestination(placeId, lat, lng) {
      const finish = (text, resolvedPlaceId) =>
        goToDestination({
          text: text || pinnedText(lat, lng),
          placeId: resolvedPlaceId || "",
          lat: lat,
          lng: lng,
        });
      google.maps
        .importLibrary("geocoding")
        .then((lib) => {
          const geocoder = new lib.Geocoder();
          const request = placeId
            ? { placeId: placeId }
            : { location: { lat: lat, lng: lng } };
          return geocoder.geocode(request);
        })
        .then((res) => {
          const best = res && res.results && res.results[0];
          if (best && best.formatted_address) {
            finish(best.formatted_address, placeId || best.place_id);
          } else {
            finish(placeId ? "Selected place" : "", placeId);
          }
        })
        .catch(() => finish(placeId ? "Selected place" : "", placeId));
    }

    // Click a POI (placeId) or any spot on the map to route there. Marker
    // and polyline clicks don't reach this listener.
    map.addListener("click", (event) => {
      if (!event.latLng) return;
      const lat = Number(event.latLng.lat().toFixed(6));
      const lng = Number(event.latLng.lng().toFixed(6));
      if (event.placeId) {
        event.stop(); // suppress the default POI info window
        resolveDestination(event.placeId, lat, lng);
      } else {
        resolveDestination("", lat, lng);
      }
    });

    // Route-option buttons live inside #route-result, which is swapped on
    // reroute — delegate so the listener survives the swap.
    document.addEventListener("click", (event) => {
      const btn =
        event.target && event.target.closest
          ? event.target.closest("[data-route-select]")
          : null;
      if (btn) selectRoute(btn.dataset.routeSelect);
    });

    // Initial data from the server-rendered page, if any.
    let initial = null;
    if (dataEl) {
      try {
        initial = JSON.parse(dataEl.textContent);
      } catch (err) {
        initial = null;
      }
    }
    applyRouteData(initial);
  }

  // --- Simulation layer (ADR-015) -----------------------------------------
  // Coarse vehicle frames arrive over ws/simulation/ (or a polling
  // fallback); markers interpolate between ticks in the browser. Gate
  // states recolour visible crossing pins via the shared status path.
  // Everything here is demo data and stays labelled as such.
  function setupSimulation(map, markerLib) {
    const bannerEl = document.getElementById("sim-banner");
    const bannerText =
      bannerEl && bannerEl.querySelector("[data-sim-banner-text]");
    if (!cfg.simulationWsUrl && !cfg.simulationUrl) return;

    const SIM_COLOR = "#7c3aed";
    const SIM_BORDER = "#5b21b6";
    const DEFAULT_TICK_MS = 5000;
    const vehicles = new Map();
    let ws = null;
    let pollTimer = null;
    let retryTimer = null;
    let attempts = 0;
    let rafId = null;

    function showBanner(text) {
      if (!bannerEl) return;
      if (bannerText) {
        bannerText.textContent =
          text || "Simulation active — vehicles & gates are demo data";
      }
      bannerEl.hidden = false;
    }

    function hideBanner() {
      if (bannerEl) bannerEl.hidden = true;
    }

    function arrowGlyph(dir) {
      const el = document.createElement("div");
      el.textContent = "▲";
      el.style.transform = "rotate(" + (dir || 0) + "deg)";
      el.style.color = "#fff";
      el.style.fontSize = "9px";
      el.style.lineHeight = "1";
      return el;
    }

    function setVehicleMap(entry, target) {
      if (entry.pin) {
        if (entry.marker.map !== target) entry.marker.map = target;
      } else if (entry.marker.getMap() !== target) {
        entry.marker.setMap(target);
      }
    }

    function setVehiclePos(entry, pos) {
      const p = { lat: pos[0], lng: pos[1] };
      if (entry.pin) entry.marker.position = p;
      else entry.marker.setPosition(p);
    }

    function makeVehicle(v) {
      const title =
        (v.label || "Simulated vehicle") + " — simulated, demo data";
      const entry = { id: v.id, pin: null, marker: null, from: null, to: null, t0: 0, t1: 0 };
      const pos = { lat: v.lat, lng: v.lng };
      if (window.vz.hasMapId && markerLib.AdvancedMarkerElement) {
        entry.pin = new markerLib.PinElement({
          background: SIM_COLOR,
          borderColor: SIM_BORDER,
          glyphColor: "#fff",
          glyph: arrowGlyph(v.dir),
          scale: 0.7,
        });
        entry.marker = new markerLib.AdvancedMarkerElement({
          map: map,
          position: pos,
          title: title,
          content: entry.pin.element,
          zIndex: 500,
        });
      } else {
        entry.marker = new markerLib.Marker({
          map: map,
          position: pos,
          title: title,
          icon: {
            path: google.maps.SymbolPath.CIRCLE,
            scale: 5,
            fillColor: SIM_COLOR,
            fillOpacity: 0.9,
            strokeColor: "#fff",
            strokeWeight: 1.5,
          },
          zIndex: 500,
        });
      }
      entry.from = [v.lat, v.lng];
      entry.to = [v.lat, v.lng];
      return entry;
    }

    function interpPos(entry, nowMs) {
      if (!entry.to) return entry.from;
      if (reducedMotion || entry.t1 <= entry.t0) return entry.to;
      const f = Math.max(0, Math.min(1, (nowMs - entry.t0) / (entry.t1 - entry.t0)));
      return [
        entry.from[0] + (entry.to[0] - entry.from[0]) * f,
        entry.from[1] + (entry.to[1] - entry.from[1]) * f,
      ];
    }

    function animate() {
      const nowMs = Date.now();
      let pending = false;
      vehicles.forEach((entry) => {
        const pos = interpPos(entry, nowMs);
        if (pos) setVehiclePos(entry, pos);
        if (entry.t1 > nowMs) pending = true;
      });
      rafId = pending ? requestAnimationFrame(animate) : null;
    }

    function scheduleAnimate() {
      if (rafId === null) rafId = requestAnimationFrame(animate);
    }

    function upsertVehicles(list, intervalMs) {
      const nowMs = Date.now();
      const seen = new Set();
      (list || []).forEach((v) => {
        if (typeof v.lat !== "number" || typeof v.lng !== "number") return;
        seen.add(v.id);
        let entry = vehicles.get(v.id);
        if (!entry) {
          entry = makeVehicle(v);
          vehicles.set(v.id, entry);
        }
        entry.from = interpPos(entry, nowMs) || entry.to;
        entry.to = [v.lat, v.lng];
        entry.t0 = nowMs;
        entry.t1 = nowMs + intervalMs;
        if (entry.pin) entry.pin.glyph = arrowGlyph(v.dir);
      });
      vehicles.forEach((entry, id) => {
        if (!seen.has(id)) {
          setVehicleMap(entry, null);
          vehicles.delete(id);
        }
      });
      if (reducedMotion) {
        vehicles.forEach((entry) => setVehiclePos(entry, entry.to));
        return;
      }
      scheduleAnimate();
    }

    function applyGates(gates, asOf) {
      if (!gates || !window.vz.applyPushedStatus) return;
      Object.keys(gates).forEach((key) => {
        const id = Number(key);
        if (!Number.isInteger(id)) return;
        const closed = gates[key] === "closed";
        window.vz.applyPushedStatus(
          id,
          {
            state: closed ? "closed_simulated" : "open_simulated",
            label: closed ? "Simulated closed" : "Simulated open",
            simulated: true,
          },
          null,
          asOf
        );
      });
    }

    function clearSim() {
      vehicles.forEach((entry) => setVehicleMap(entry, null));
      vehicles.clear();
      hideBanner();
      if (window.vz.requestCrossingLoad) {
        // Gates reverted server-side; fetch fresh effective statuses now.
        window.vz.requestCrossingLoad(true);
      }
    }

    function handleMessage(msg) {
      if (!msg || typeof msg !== "object") return;
      const tickMs =
        msg.run && msg.run.tick_seconds
          ? Math.max(500, msg.run.tick_seconds * 1000)
          : DEFAULT_TICK_MS;
      switch (msg.type) {
        case "sim.snapshot":
        case "sim.tick":
          showBanner();
          upsertVehicles(msg.vehicles, tickMs);
          applyGates(msg.gates, msg.at);
          break;
        case "sim.run.started":
          showBanner();
          subscribe(msg.run && msg.run.id);
          break;
        case "sim.run.paused":
          showBanner("Simulation paused — demo data");
          break;
        case "sim.run.resumed":
          showBanner();
          break;
        case "sim.run.stopped":
        case "sim.run.finished":
        case "sim.run.failed":
        case "sim.idle":
          clearSim();
          break;
        default:
          break;
      }
    }

    function subscribe(runId) {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(
          JSON.stringify(
            runId ? { type: "subscribe", run_id: runId } : { type: "subscribe" }
          )
        );
      } else {
        pollOnce();
      }
    }

    function connect() {
      if (!cfg.simulationWsUrl || attempts >= 10) {
        startPolling();
        return;
      }
      let sock;
      try {
        sock = new WebSocket(cfg.simulationWsUrl);
      } catch (err) {
        attempts = 10;
        startPolling();
        return;
      }
      ws = sock;
      sock.onopen = () => {
        attempts = 0;
        stopPolling();
        subscribe();
      };
      sock.onmessage = (event) => {
        try {
          handleMessage(JSON.parse(event.data));
        } catch (err) {
          /* malformed frame — ignore */
        }
      };
      sock.onerror = () => {
        try {
          sock.close();
        } catch (err) {
          /* closing an errored socket must not throw */
        }
      };
      sock.onclose = () => {
        if (ws !== sock) return;
        ws = null;
        attempts += 1;
        startPolling();
        if (attempts >= 10) return;
        const delay =
          Math.min(30000, 1000 * Math.pow(2, attempts)) +
          Math.floor(Math.random() * 500);
        retryTimer = setTimeout(connect, delay);
      };
    }

    // Polling fallback: same payloads, coarser cadence, only while the
    // WS is down. Covers proxies that block WebSockets.
    function pollOnce() {
      if (!cfg.simulationUrl || document.hidden) return;
      fetch(cfg.simulationUrl, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
      })
        .then((r) => (r.ok ? r.json() : null))
        .then((body) => {
          if (!body) return;
          if (body.active) {
            handleMessage({
              type: "sim.tick",
              run: body.run,
              vehicles: body.vehicles,
              gates: body.gates,
              at: body.as_of,
            });
          } else {
            handleMessage({ type: "sim.idle" });
          }
        })
        .catch(() => {});
    }

    function startPolling() {
      if (pollTimer !== null || !cfg.simulationUrl) return;
      pollTimer = setInterval(pollOnce, DEFAULT_TICK_MS);
      pollOnce();
    }

    function stopPolling() {
      if (pollTimer !== null) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    }

    window.addEventListener("online", () => {
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        attempts = 0;
        connect();
      }
    });

    connect();
    // One immediate poll so an already-running sim shows up fast even
    // while the socket handshake is in flight.
    pollOnce();
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
        // A click sets a route destination, so double-click must not zoom
        // (it fires two click events and would reroute to the same spot).
        disableDoubleClickZoom: true,
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
      try {
        setupSimulation(map, markerLib);
      } catch (err) {
        console.warn("Simulation layer failed to initialise:", err);
      }
    } catch (err) {
      showApiError();
    }
  }

  init();
})();
