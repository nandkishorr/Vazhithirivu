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
  const locBlocks = {
    idle: document.getElementById("loc-idle"),
    requesting: document.getElementById("loc-requesting"),
    active: document.getElementById("loc-active"),
    denied: document.getElementById("loc-denied"),
    unavailable: document.getElementById("loc-unavailable"),
  };
  const locateBtn = document.getElementById("locate-btn");
  const locateStop = document.getElementById("locate-stop");
  const locErrorBody = document.querySelector("[data-loc-error-body]");

  // One-shot, click-only requests. A token makes late callbacks into
  // no-ops after Stop or a newer request; coordinates never leave the
  // browser.
  let locToken = 0;
  let locInFlight = false;

  function showLocState(name) {
    Object.keys(locBlocks).forEach((key) => {
      if (locBlocks[key]) locBlocks[key].hidden = key !== name;
    });
  }

  function setLocError(message) {
    if (locErrorBody) locErrorBody.textContent = message;
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

  function onLocationSuccess(position) {
    const lat = position.coords.latitude;
    const lng = position.coords.longitude;
    const accuracy = position.coords.accuracy;
    const note = document.querySelector("[data-loc-note]");

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
      if (note) {
        let text =
          "Showing your approximate location (" +
          formatAccuracy(accuracy) +
          ").";
        if (accuracy > 1000) {
          text +=
            " This fix is imprecise \u2014 nearby crossings may be misjudged.";
        }
        note.textContent = text;
      }
    } else if (note) {
      note.textContent =
        "Your approximate location was found, but the map is unavailable.";
    }

    setFromField("My location");
    setOriginCoords(lat, lng);
    clearOriginPlaceId();
    showLocState("active");
  }

  function onLocationError(error) {
    if (error && error.code === 1) {
      showLocState("denied");
      return;
    }
    let message = "Couldn't determine your location.";
    if (error && error.code === 2) {
      message = "Your device couldn't determine a position right now.";
    } else if (error && error.code === 3) {
      message = "Finding your location took too long. Try again.";
    }
    setLocError(message);
    showLocState("unavailable");
  }

  function requestLocation() {
    if (locInFlight) return;
    if (!("geolocation" in navigator)) {
      setLocError("This browser doesn't support location.");
      showLocState("unavailable");
      return;
    }
    if (!window.isSecureContext) {
      setLocError(
        "Location needs a secure (HTTPS) connection. localhost works for development."
      );
      showLocState("unavailable");
      return;
    }
    locInFlight = true;
    const token = ++locToken;
    showLocState("requesting");
    navigator.geolocation.getCurrentPosition(
      (position) => {
        locInFlight = false;
        if (token !== locToken) return;
        onLocationSuccess(position);
      },
      (error) => {
        locInFlight = false;
        if (token !== locToken) return;
        onLocationError(error);
      },
      { enableHighAccuracy: false, timeout: 15000, maximumAge: 60000 }
    );
  }

  if (locateBtn) {
    locateBtn.addEventListener("click", requestLocation);
  }
  document.querySelectorAll("[data-locate-retry]").forEach((btn) => {
    btn.addEventListener("click", requestLocation);
  });

  if (locateStop) {
    locateStop.addEventListener("click", () => {
      locToken += 1;
      locInFlight = false;
      clearLocVisuals();
      if (currentFromText() === "My location") setFromField("");
      setOriginCoords(null, null);
      showLocState("idle");
    });
  }

  // If the user edits From to something other than "My location", drop the
  // coords so the server never sees them alongside a typed place.
  const routeForm = document.getElementById("route-form");
  if (routeForm) {
    routeForm.addEventListener("submit", () => {
      if (currentFromText() !== "My location") setOriginCoords(null, null);
    });
  }
})();
