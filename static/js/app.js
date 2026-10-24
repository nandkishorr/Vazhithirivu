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

  function showLocState(name) {
    Object.keys(locBlocks).forEach((key) => {
      if (locBlocks[key]) locBlocks[key].hidden = key !== name;
    });
  }

  function setFromField(value) {
    const input = document.getElementById("id_origin");
    if (input) input.value = value;
    const autocomplete =
      input && input.parentElement
        ? input.parentElement.querySelector("gmp-place-autocomplete")
        : null;
    if (autocomplete) autocomplete.value = value;
  }

  function onLocationSuccess(position) {
    const lat = position.coords.latitude;
    const lng = position.coords.longitude;
    const note = document.querySelector("[data-loc-note]");

    if (window.vz && window.vz.map) {
      const center = { lat: lat, lng: lng };
      if (window.vz.reducedMotion) {
        window.vz.map.setCenter(center);
      } else {
        window.vz.map.panTo(center);
      }
      if (window.vz.hasMapId && window.vz.AdvancedMarkerElement) {
        if (window.vz.userMarker) window.vz.userMarker.map = null;
        window.vz.userMarker = new window.vz.AdvancedMarkerElement({
          map: window.vz.map,
          position: center,
          title: "Your approximate location",
        });
        if (note) note.textContent = "Showing your approximate location on the map.";
      } else if (note) {
        note.textContent =
          "Map panned to your approximate location. No marker is shown because GOOGLE_MAPS_MAP_ID isn't configured.";
      }
    } else if (note) {
      note.textContent =
        "Your approximate location was found, but the map is unavailable.";
    }

    setFromField("My location");
    showLocState("active");
  }

  function onLocationError(error) {
    if (error && error.code === 1) {
      showLocState("denied");
    } else {
      showLocState("unavailable");
    }
  }

  if (locateBtn) {
    locateBtn.addEventListener("click", () => {
      if (!navigator.geolocation) {
        showLocState("unavailable");
        return;
      }
      showLocState("requesting");
      navigator.geolocation.getCurrentPosition(onLocationSuccess, onLocationError, {
        enableHighAccuracy: false,
        timeout: 10000,
        maximumAge: 60000,
      });
    });
  }

  if (locateStop) {
    locateStop.addEventListener("click", () => {
      if (window.vz && window.vz.userMarker) {
        window.vz.userMarker.map = null;
        window.vz.userMarker = null;
      }
      showLocState("idle");
    });
  }
})();
