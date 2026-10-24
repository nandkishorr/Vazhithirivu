(function () {
  "use strict";

  // --- Mobile bottom sheet -------------------------------------------------
  const panel = document.getElementById("route-panel");
  const toggle = document.getElementById("sheet-toggle");

  function setSheet(expanded) {
    if (!panel || !toggle) return;
    panel.classList.toggle("sheet-collapsed", !expanded);
    toggle.setAttribute("aria-expanded", expanded ? "true" : "false");
    const chevron = toggle.querySelector("[data-chevron]");
    if (chevron) chevron.style.transform = expanded ? "rotate(180deg)" : "";
  }

  // Let map.js expand a collapsed mobile sheet (e.g. on marker click).
  window.vz = window.vz || {};
  window.vz.expandSheet = function () {
    setSheet(true);
  };

  if (toggle) {
    toggle.addEventListener("click", () => {
      setSheet(panel.classList.contains("sheet-collapsed"));
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") setSheet(false);
    });
  }

  // --- Geolocation (explicit opt-in only) -----------------------------------
  // "My location" is the default route origin. The *choice* is persisted
  // in localStorage; coordinates never are — a fresh fix is requested per
  // session and a fix is only requested automatically when the browser
  // already reports geolocation as granted (ADR-005).
  const MY_LOC_TEXT = "My location";
  const MY_LOC_PREF = "vz.origin.myLocation";

  const locateBtn = document.getElementById("locate-btn");
  const locAlert = document.getElementById("loc-alert");
  const locAlertBody =
    locAlert && locAlert.querySelector("[data-loc-alert-body]");
  const locAlertDismiss =
    locAlert && locAlert.querySelector("[data-loc-alert-dismiss]");

  // One-shot requests. A token makes late callbacks into no-ops after a
  // newer request; coordinates never leave the browser except as route
  // form fields on explicit submit.
  let locToken = 0;
  let locInFlight = false;
  let myLocPos = null;
  const locCallbacks = [];
  let locAlertTimer = null;

  const LOC_VARIANTS = {
    info: "border-sky-200 bg-sky-50 text-sky-900",
    ok: "border-teal-200 bg-teal-50 text-teal-900",
    error: "border-red-200 bg-red-50 text-red-900",
  };
  const LOC_ALERT_BASE =
    "mt-1 flex items-start gap-2 rounded-lg border px-2.5 py-1.5 text-xs";

  function hideLocAlert() {
    if (locAlertTimer) {
      clearTimeout(locAlertTimer);
      locAlertTimer = null;
    }
    if (locAlert) locAlert.hidden = true;
  }

  function showLocAlert(variant, message, opts) {
    if (!locAlert) return;
    locAlert.className =
      LOC_ALERT_BASE + " " + (LOC_VARIANTS[variant] || LOC_VARIANTS.info);
    locAlert.setAttribute("role", variant === "error" ? "alert" : "status");
    if (locAlertBody) locAlertBody.textContent = message;
    locAlert.hidden = false;
    if (locAlertTimer) clearTimeout(locAlertTimer);
    locAlertTimer =
      opts && opts.sticky
        ? null
        : setTimeout(hideLocAlert, (opts && opts.timeout) || 8000);
  }

  if (locAlertDismiss) {
    locAlertDismiss.addEventListener("click", hideLocAlert);
  }

  function flushLocCallbacks(pos) {
    locCallbacks.splice(0).forEach((cb) => {
      try {
        cb(pos);
      } catch (err) {
        /* a broken caller must not break location */
      }
    });
  }

  // gmpx-place-picker keeps its text box in an open shadow root; reading
  // is guarded so a Google internals change degrades to "".
  function pickerInput(picker) {
    try {
      return (
        picker &&
        picker.shadowRoot &&
        picker.shadowRoot.querySelector("input")
      );
    } catch (err) {
      return null;
    }
  }

  function currentFromText() {
    const picker = document.getElementById("origin-picker");
    const el = pickerInput(picker);
    if (el) return el.value;
    const input = document.getElementById("id_origin");
    return input ? input.value : "";
  }

  function setFromField(value) {
    const input = document.getElementById("id_origin");
    if (input) input.value = value;
    const el = pickerInput(document.getElementById("origin-picker"));
    if (el) el.value = value;
  }

  // "My location" coords travel to the server only as form fields when the
  // user explicitly submits Find route (opt-in); they are never stored.
  function setOriginCoords(lat, lng) {
    const latEl = document.getElementById("id_origin_lat");
    const lngEl = document.getElementById("id_origin_lng");
    if (latEl) latEl.value = lat === null ? "" : String(lat);
    if (lngEl) lngEl.value = lng === null ? "" : String(lng);
  }

  function clearOriginPlaceId() {
    const placeId = document.getElementById("id_origin_place_id");
    if (placeId) placeId.value = "";
  }

  function clearLocVisuals() {
    if (window.vz && window.vz.userMarker) {
      window.vz.userMarker.map = null;
      window.vz.userMarker = null;
    }
    if (window.vz && window.vz.userCircle) {
      window.vz.userCircle.setMap(null);
      window.vz.userCircle = null;
    }
  }

  function formatAccuracy(meters) {
    if (meters >= 1000) return "\u00b1" + (meters / 1000).toFixed(1) + " km";
    return "\u00b1" + Math.round(meters) + " m";
  }

  function hasOriginCoords() {
    const latEl = document.getElementById("id_origin_lat");
    const lngEl = document.getElementById("id_origin_lng");
    return Boolean(latEl && latEl.value && lngEl && lngEl.value);
  }

  // After a fresh fix, re-plan when the page already has a destination and
  // the origin changed (or the URL was planned without coords).
  function maybeAutoReroute(explicit) {
    try {
      const qs = new URLSearchParams(window.location.search);
      if (!qs.get("destination")) return;
      if (!explicit && qs.get("origin_lat")) return;
      if (window.vz && window.vz.reroute) window.vz.reroute();
    } catch (err) {
      /* never let rerouting break a location fix */
    }
  }

  function onLocationSuccess(position, explicit) {
    const lat = position.coords.latitude;
    const lng = position.coords.longitude;
    const accuracy = position.coords.accuracy;
    myLocPos = { lat: lat, lng: lng };
    try {
      localStorage.setItem(MY_LOC_PREF, "1");
    } catch (err) {
      /* private mode — persistence is best-effort */
    }

    if (window.vz && window.vz.map) {
      const map = window.vz.map;
      const center = { lat: lat, lng: lng };
      if (window.vz.reducedMotion) {
        map.setCenter(center);
      } else {
        map.panTo(center);
      }
      if (map.getZoom() < (window.vz.crossingsMinZoom || 0)) {
        map.setZoom(15);
      }
      clearLocVisuals();
      if (window.vz.hasMapId && window.vz.AdvancedMarkerElement) {
        window.vz.userMarker = new window.vz.AdvancedMarkerElement({
          map: map,
          position: center,
          title: "Your approximate location",
        });
      }
      if (window.vz.Circle) {
        window.vz.userCircle = new window.vz.Circle({
          map: map,
          center: center,
          radius: accuracy,
          strokeColor: "#0d9488",
          strokeOpacity: 0.6,
          strokeWeight: 1,
          fillColor: "#14b8a6",
          fillOpacity: 0.12,
          clickable: false,
        });
      }
    }

    setFromField(MY_LOC_TEXT);
    setOriginCoords(lat, lng);
    clearOriginPlaceId();
    let note = "Using your location (" + formatAccuracy(accuracy) + ").";
    if (accuracy > 1000) {
      note +=
        " This fix is imprecise — nearby crossings may be misjudged.";
    }
    showLocAlert("ok", note, { timeout: 6000 });
    flushLocCallbacks(myLocPos);
    maybeAutoReroute(explicit);
  }

  function onLocationError(error) {
    let message = "Couldn't determine your location.";
    if (error && error.code === 1) {
      message =
        "Location permission denied — enable it in your browser's site " +
        "settings, then try Use my location again.";
    } else if (error && error.code === 2) {
      message = "Your device couldn't determine a position right now.";
    } else if (error && error.code === 3) {
      message = "Finding your location took too long. Try again.";
    }
    showLocAlert("error", message, { sticky: true });
    flushLocCallbacks(null);
  }

  // explicit = user-triggered (button, submit, pending route) vs a silent
  // startup fix when the browser already grants geolocation.
  function requestLocation(explicit) {
    if (locInFlight) return;
    if (!("geolocation" in navigator)) {
      showLocAlert("error", "This browser doesn't support location.", {
        sticky: true,
      });
      flushLocCallbacks(null);
      return;
    }
    if (!window.isSecureContext) {
      showLocAlert(
        "error",
        "Location needs a secure (HTTPS) connection. localhost works for development.",
        { sticky: true }
      );
      flushLocCallbacks(null);
      return;
    }
    locInFlight = true;
    const token = ++locToken;
    showLocAlert("info", "Finding your location…", { sticky: true });
    navigator.geolocation.getCurrentPosition(
      (position) => {
        locInFlight = false;
        if (token !== locToken) return;
        onLocationSuccess(position, explicit);
      },
      (error) => {
        locInFlight = false;
        if (token !== locToken) return;
        onLocationError(error);
      },
      { enableHighAccuracy: false, timeout: 15000, maximumAge: 60000 }
    );
  }

  // API used by map.js rerouting and by the locate button.
  window.vz.requestMyLocation = function (callback) {
    if (callback) locCallbacks.push(callback);
    requestLocation(true);
  };
  window.vz.getMyLocation = function () {
    return myLocPos;
  };
  window.vz.clearMyLocation = function () {
    locToken += 1;
    locInFlight = false;
    myLocPos = null;
    try {
      localStorage.setItem(MY_LOC_PREF, "0");
    } catch (err) {
      /* persistence is best-effort */
    }
    clearLocVisuals();
    setOriginCoords(null, null);
    hideLocAlert();
  };

  if (locateBtn) {
    locateBtn.addEventListener("click", () => {
      window.vz.requestMyLocation();
    });
  }

  // Picking a real place for From supersedes "My location".
  const originPicker = document.getElementById("origin-picker");
  if (originPicker) {
    originPicker.addEventListener("gmpx-placechange", () => {
      const place = originPicker.value;
      if (place && place.id) window.vz.clearMyLocation();
    });
  }

  // The picker's text box lives in a (possibly not-yet-upgraded) shadow
  // root; seed it once the element exists so reloads show saved values.
  function seedPickerText(pickerId, text) {
    if (!text) return;
    const apply = () => {
      const el = pickerInput(document.getElementById(pickerId));
      if (el) el.value = text;
    };
    apply();
    if (window.customElements && customElements.whenDefined) {
      customElements
        .whenDefined("gmpx-place-picker")
        .then(apply)
        .catch(() => {});
    }
  }

  // Default the origin to "My location" (unless the user opted out or the
  // page already carries an origin), then resolve coords only when the
  // browser already grants geolocation — otherwise show an alert nudge.
  (function initOriginDefault() {
    const originInput = document.getElementById("id_origin");
    const destinationInput = document.getElementById("id_destination");
    if (destinationInput && destinationInput.value) {
      seedPickerText("destination-picker", destinationInput.value);
    }
    if (!originInput) return;
    let pref = null;
    try {
      pref = localStorage.getItem(MY_LOC_PREF);
    } catch (err) {
      pref = null;
    }
    if (!originInput.value.trim() && pref !== "0") {
      originInput.value = MY_LOC_TEXT;
    }
    if (originInput.value) {
      seedPickerText("origin-picker", originInput.value);
    }
    // A reload of a "My location" route carries the fix in the form fields
    // — reuse it instead of requesting a redundant one.
    if (currentFromText() === MY_LOC_TEXT && hasOriginCoords()) {
      myLocPos = {
        lat: parseFloat(document.getElementById("id_origin_lat").value),
        lng: parseFloat(document.getElementById("id_origin_lng").value),
      };
      return;
    }
    if (currentFromText() !== MY_LOC_TEXT) return;
    const enableMsg =
      "Allow location access to start routes from your position.";
    const deniedMsg =
      "Location is blocked in your browser settings — enable it to start " +
      "routes from your position.";
    const onState = (state) => {
      if (state === "granted") {
        requestLocation(false); // silent fix: the browser won't prompt
      } else if (state === "denied") {
        showLocAlert("error", deniedMsg, { sticky: true });
      } else {
        showLocAlert("info", enableMsg, { sticky: true });
      }
    };
    if (navigator.permissions && navigator.permissions.query) {
      navigator.permissions
        .query({ name: "geolocation" })
        .then((result) => onState(result.state))
        .catch(() => onState("prompt"));
    } else {
      onState("prompt");
    }
  })();

  // If the user edits From to something other than "My location", drop the
  // coords so the server never sees them alongside a typed place.
  const routeForm = document.getElementById("route-form");
  if (routeForm) {
    routeForm.addEventListener("submit", (event) => {
      if (currentFromText() === MY_LOC_TEXT) {
        if (!myLocPos) {
          // "My location" needs a fix first; continue the submit after it.
          event.preventDefault();
          window.vz.requestMyLocation((pos) => {
            if (pos) routeForm.requestSubmit();
          });
        }
        return;
      }
      if (myLocPos) window.vz.clearMyLocation();
      setOriginCoords(null, null);
      if (currentFromText().trim()) {
        try {
          localStorage.setItem(MY_LOC_PREF, "0");
        } catch (err) {
          /* persistence is best-effort */
        }
      }
    });
  }
})();
