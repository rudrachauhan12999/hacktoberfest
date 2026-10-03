// The scan sheet: choose label or meal, add a photo (upload, drag, or camera), analyze.

import { $, $$, api, icon } from "./ui.js";

const dialog = $("#scan");
const video = $("#camera-video");
const analyze = $("#btn-analyze");
const LOADING = {
  label: ["Reading the label", "Checking the numbers"],
  meal: ["Estimating the meal", "Checking the numbers"],
};

let mode = "label";
let photo = null;        // a File or Blob
let photoUrl = null;
let stream = null;
let busy = false;
let onResult = () => {};

export function initScan(callback) {
  onResult = callback;
  $("#scan-close").innerHTML = icon("close");
  $$("[data-icon]", dialog).forEach((slot) => { slot.outerHTML = icon(slot.dataset.icon); });

  $$("[data-mode]", dialog).forEach((button) =>
    button.addEventListener("click", () => setMode(button.dataset.mode)));
  $("#btn-upload").addEventListener("click", () => $("#file-input").click());
  $("#btn-camera").addEventListener("click", startCamera);
  $("#camera-capture").addEventListener("click", capture);
  $("#camera-cancel").addEventListener("click", () => { stopCamera(); show(); });
  $("#preview-remove").addEventListener("click", () => { setPhoto(null); $("#btn-upload").focus(); });
  for (const id of ["#file-input", "#capture-input"]) {
    $(id).addEventListener("change", (event) => {
      if (event.target.files[0]) setPhoto(event.target.files[0]);
      event.target.value = "";
    });
  }
  $("#desc").addEventListener("input", (event) => {
    $("#desc-count").textContent = event.target.value.length;
  });

  const drop = $("#drop");
  drop.addEventListener("dragover", (event) => { event.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (event) => {
    event.preventDefault();
    drop.classList.remove("over");
    const file = [...event.dataTransfer.files].find((f) => f.type.startsWith("image/"));
    if (file) setPhoto(file); else showError("Drop an image file, such as a JPEG or PNG photo.");
  });

  analyze.addEventListener("click", submit);
  dialog.addEventListener("close", stopCamera);
  dialog.addEventListener("cancel", (event) => { if (busy) event.preventDefault(); });
  dialog.addEventListener("click", (event) => { if (event.target === dialog && !busy) dialog.close(); });
}

export function openScan() {
  setPhoto(null);
  $("#desc").value = "";
  $("#desc-count").textContent = "0";
  setMode(mode);
  dialog.showModal();
}

// ------------------------------------------------------------------ state

function setMode(next) {
  mode = next;
  $$("[data-mode]", dialog).forEach((button) =>
    button.setAttribute("aria-pressed", String(button.dataset.mode === mode)));
  $("#desc-wrap").hidden = mode !== "meal";
  $("#drop-hint").textContent = mode === "label"
    ? "Or drag a photo of the nutrition table here."
    : "Or drag a photo of the meal here.";
  showError("");
}

// Show exactly one of: the two big buttons, the live camera, or the preview.
function show() {
  $("#drop-choose").hidden = Boolean(photo) || Boolean(stream);
  $("#camera").hidden = !stream;
  $("#preview").hidden = !photo;
}

function setPhoto(file) {
  stopCamera();
  if (photoUrl) URL.revokeObjectURL(photoUrl);
  photo = file;
  photoUrl = file ? URL.createObjectURL(file) : null;
  if (photoUrl) $("#preview-img").src = photoUrl; else $("#preview-img").removeAttribute("src");
  showError("");
  show();
}

function showError(message) {
  const box = $("#scan-error");
  box.textContent = message;
  box.hidden = !message;
}

// ----------------------------------------------------------------- camera

async function startCamera() {
  showError("");
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    $("#capture-input").click();
    return;
  }
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 } },
      audio: false,
    });
  } catch {
    stream = null;
    // Camera denied or missing: fall back to the device's own capture or file picker.
    showError("The camera is not available here. Choose a photo instead.");
    $("#capture-input").click();
    return;
  }
  video.srcObject = stream;
  show();
  await video.play().catch(() => {});
  $("#camera-capture").focus();
}

function stopCamera() {
  if (stream) stream.getTracks().forEach((track) => track.stop());
  stream = null;
  video.srcObject = null;
}

function capture() {
  if (!video.videoWidth) return;
  const canvas = document.createElement("canvas");
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  canvas.getContext("2d").drawImage(video, 0, 0);
  canvas.toBlob((blob) => { if (blob) setPhoto(blob); }, "image/jpeg", 0.92);
}

// ---------------------------------------------------------------- analyze

function setBusy(on) {
  busy = on;
  analyze.disabled = on;
  $$("button, textarea", dialog).forEach((el) => { if (el !== analyze) el.disabled = on; });
  if (!on) { analyze.textContent = "Analyze"; return null; }
  const steps = LOADING[mode];
  let index = 0;
  const paint = () => {
    analyze.innerHTML = `<span class="spinner" aria-hidden="true"></span><span aria-live="polite">${steps[index % steps.length]}</span>`;
    index += 1;
  };
  paint();
  return setInterval(paint, 2200);
}

async function submit() {
  if (busy) return;
  const description = $("#desc").value.trim();
  if (mode === "label" && !photo) { showError("Add a photo of the nutrition label first."); return; }
  if (mode === "meal" && !photo && !description) { showError("Add a photo, a description, or both."); return; }

  const form = new FormData();
  if (photo) form.append("image", photo, "photo.jpg");
  if (mode === "meal") form.append("description", description);

  showError("");
  const ticker = setBusy(true);
  try {
    const result = await api(`/api/scan/${mode}`, { method: "POST", form });
    if (result.needs_retake) {
      showError(result.message);
      return;
    }
    // Hand the photo's object URL to the detail view; it must outlive this sheet.
    const url = photoUrl;
    photoUrl = null;
    dialog.close();
    onResult({ ...result, photoUrl: url });
  } catch (error) {
    showError(error.message);
  } finally {
    clearInterval(ticker);
    setBusy(false);
  }
}
