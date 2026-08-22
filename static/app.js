const chat = document.getElementById("chat");
const form = document.getElementById("form-mensaje");
const input = document.getElementById("input-texto");
const btnMic = document.getElementById("btn-mic");
const vozToggle = document.getElementById("voz-toggle");
const orb = document.getElementById("orb");
const orbLabel = document.getElementById("orb-label");
const reproductorWrap = document.getElementById("reproductor-wrap");
const btnCerrarReproductor = document.getElementById("btn-cerrar-reproductor");

// --- Reproductor de YouTube vía API oficial (necesaria para detectar videos
// que el dueño no deja embeber fuera de youtube.com, y probar el siguiente) ---
let ytPlayer = null;
let ytApiListo = false;
let candidatosActuales = [];
let candidatoIndex = 0;

const tagYt = document.createElement("script");
tagYt.src = "https://www.youtube.com/iframe_api";
document.head.appendChild(tagYt);

window.onYouTubeIframeAPIReady = () => {
  ytApiListo = true;
};

function reproducirCandidatos(candidatos) {
  candidatosActuales = candidatos || [];
  candidatoIndex = 0;
  if (!candidatosActuales.length) return;
  reproductorWrap.classList.remove("oculto");
  intentarReproducirActual();
}

function intentarReproducirActual() {
  if (candidatoIndex >= candidatosActuales.length) {
    agregarBurbuja("Ese tema no se puede reproducir acá (YouTube no deja incrustarlo) 😕 Probá pedir otra versión.", "bot");
    reproductorWrap.classList.add("oculto");
    return;
  }

  if (!ytApiListo || !window.YT || !window.YT.Player) {
    setTimeout(intentarReproducirActual, 300);
    return;
  }

  const videoId = candidatosActuales[candidatoIndex].video_id;

  if (ytPlayer) {
    ytPlayer.loadVideoById(videoId);
    return;
  }

  ytPlayer = new YT.Player("reproductor", {
    videoId,
    width: "100%",
    height: "100%",
    playerVars: { autoplay: 1 },
    events: {
      onReady: (e) => {
        const iframe = e.target.getIframe();
        iframe.style.width = "100%";
        iframe.style.height = "100%";
      },
      onError: () => {
        candidatoIndex += 1;
        intentarReproducirActual();
      },
    },
  });
}

btnCerrarReproductor.addEventListener("click", () => {
  if (ytPlayer && ytPlayer.stopVideo) ytPlayer.stopVideo();
  reproductorWrap.classList.add("oculto");
});

const ETIQUETAS_ESTADO = {
  idle: "en reposo",
  escuchando: "escuchando...",
  pensando: "pensando...",
  hablando: "hablando...",
};

function setEstado(estado) {
  orb.dataset.estado = estado;
  orbLabel.textContent = ETIQUETAS_ESTADO[estado] || estado;
}

function agregarBurbuja(texto, quien) {
  const div = document.createElement("div");
  div.className = `msg ${quien}`;
  div.textContent = texto;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
  return div;
}

// iOS Safari exige que el primer speechSynthesis.speak() de la sesión ocurra
// directamente dentro de un toque del usuario, si no lo bloquea en silencio.
// Este "desbloqueo" corre una sola vez, en la primera interacción con la página.
let vozDesbloqueada = false;
let vocesCache = [];

function refrescarVoces() {
  const voces = window.speechSynthesis.getVoices();
  if (voces.length) vocesCache = voces;
}

if ("speechSynthesis" in window) {
  refrescarVoces();
  window.speechSynthesis.onvoiceschanged = refrescarVoces;

  const desbloquearVoz = () => {
    if (vozDesbloqueada) return;
    vozDesbloqueada = true;
    const utterVacio = new SpeechSynthesisUtterance("");
    utterVacio.volume = 0;
    window.speechSynthesis.speak(utterVacio);
    document.removeEventListener("touchend", desbloquearVoz);
    document.removeEventListener("click", desbloquearVoz);
  };
  document.addEventListener("touchend", desbloquearVoz, { once: true });
  document.addEventListener("click", desbloquearVoz, { once: true });
}

function hablar(texto) {
  if (!vozToggle.checked || !("speechSynthesis" in window)) {
    setEstado("idle");
    return;
  }
  window.speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(texto);
  utter.lang = "es-ES";
  const vozEs = vocesCache.find(v => v.lang && v.lang.startsWith("es"));
  if (vozEs) utter.voice = vozEs;
  utter.onstart = () => setEstado("hablando");
  utter.onend = () => setEstado("idle");
  utter.onerror = () => setEstado("idle");
  window.speechSynthesis.speak(utter);
}

function mostrarRespuesta(datos) {
  agregarBurbuja(datos.respuesta, "bot");
  if (datos.video_candidatos && datos.video_candidatos.length) {
    reproducirCandidatos(datos.video_candidatos);
    setEstado("idle");
  } else {
    hablar(datos.respuesta);
  }
}

async function enviarMensaje(texto) {
  texto = texto.trim();
  if (!texto) return;

  agregarBurbuja(texto, "user");
  input.value = "";

  setEstado("pensando");
  const pensando = agregarBurbuja("Pensando...", "bot pensando");

  try {
    const resp = await fetch("/api/mensaje", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ texto }),
    });
    const datos = await resp.json();
    pensando.remove();
    mostrarRespuesta(datos);
  } catch (e) {
    pensando.remove();
    agregarBurbuja("No pude conectarme con el servidor 😕", "bot");
    setEstado("idle");
  }
}

async function enviarAudio(blob, extension) {
  setEstado("pensando");
  const pensando = agregarBurbuja("Pensando...", "bot pensando");

  const formData = new FormData();
  formData.append("archivo", blob, extension);

  try {
    const resp = await fetch("/api/audio", { method: "POST", body: formData });
    const datos = await resp.json();
    pensando.remove();
    if (datos.transcripcion) agregarBurbuja(datos.transcripcion, "user");
    mostrarRespuesta(datos);
  } catch (e) {
    pensando.remove();
    agregarBurbuja("No pude conectarme con el servidor 😕", "bot");
    setEstado("idle");
  }
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  enviarMensaje(input.value);
});

// --- Entrada de voz: reconocimiento nativo solo en Chrome/Edge (es confiable ahí).
// En cualquier navegador con motor WebKit (Safari, Chrome/Edge de iOS, que comparten
// el mismo motor) el reconocimiento nativo existe pero falla en silencio muy seguido,
// así que ahí directamente grabamos y transcribimos con Whisper en el servidor. ---
const SpeechRecognitionAPI = window.SpeechRecognition || window.webkitSpeechRecognition;
const uaEsWebKit = /CriOS|EdgiOS|FxiOS|Safari/.test(navigator.userAgent) && !/Chrome\/|Edg\//.test(navigator.userAgent);
const usarReconocimientoNativo = !!SpeechRecognitionAPI && !uaEsWebKit;
let grabando = false;

if (usarReconocimientoNativo) {
  const reconocimiento = new SpeechRecognitionAPI();
  reconocimiento.lang = "es-ES";
  reconocimiento.interimResults = false;
  reconocimiento.maxAlternatives = 1;

  reconocimiento.onstart = () => setEstado("escuchando");

  reconocimiento.onresult = (event) => {
    const texto = event.results[0][0].transcript;
    enviarMensaje(texto);
  };

  reconocimiento.onerror = (event) => {
    grabando = false;
    btnMic.classList.remove("grabando");
    setEstado("idle");
    if (event.error !== "aborted" && event.error !== "no-speech") {
      agregarBurbuja(`No entendí el audio (${event.error}) 😕 Probá de nuevo.`, "bot");
    }
  };

  reconocimiento.onend = () => {
    grabando = false;
    btnMic.classList.remove("grabando");
  };

  btnMic.addEventListener("click", () => {
    if (grabando) {
      reconocimiento.stop();
      return;
    }
    grabando = true;
    btnMic.classList.add("grabando");
    reconocimiento.start();
  });
} else if (navigator.mediaDevices && window.MediaRecorder) {
  let mediaRecorder = null;
  let trozos = [];

  btnMic.addEventListener("click", async () => {
    if (grabando) {
      mediaRecorder.stop();
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = MediaRecorder.isTypeSupported("audio/mp4") ? "audio/mp4" : "";
      mediaRecorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
      trozos = [];

      mediaRecorder.ondataavailable = (e) => trozos.push(e.data);

      mediaRecorder.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        grabando = false;
        btnMic.classList.remove("grabando");
        const tipo = mediaRecorder.mimeType || "audio/mp4";
        const blob = new Blob(trozos, { type: tipo });
        const extension = tipo.includes("mp4") ? "audio.mp4" : tipo.includes("webm") ? "audio.webm" : "audio.ogg";
        enviarAudio(blob, extension);
      };

      mediaRecorder.start();
      grabando = true;
      btnMic.classList.add("grabando");
      setEstado("escuchando");
    } catch (e) {
      agregarBurbuja("No pude acceder al micrófono 😕 (revisá los permisos del navegador)", "bot");
    }
  });
} else {
  btnMic.disabled = true;
  btnMic.title = "Tu navegador no soporta entrada de voz";
}

agregarBurbuja("¡Hola! Escribime o tocá el micrófono para hablarme.", "bot");
