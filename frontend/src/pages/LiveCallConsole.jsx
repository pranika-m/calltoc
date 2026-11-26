import { useEffect, useRef, useState } from "react";
import {
  Mic,
  MicOff,
  Phone,
  PhoneOff,
  Hand,
  BookOpen,
  CalendarCheck,
  AlertTriangle,
  Sparkles,
  Volume2,
  VolumeX,
} from "lucide-react";
import { VoiceOrb } from "../components/VoiceOrb";
import { ScoreGauge } from "../components/ScoreGauge";

const WS_BASE = import.meta.env.VITE_WS_BASE || "ws://localhost:8000";

const STATE_LABELS = {
  idle: "Ready to talk",
  connecting: "Connecting…",
  listening: "Listening…",
  processing: "Thinking…",
  speaking: "Speaking…",
  ended: "Call ended",
  error: "Connection lost, reconnecting…",
};

function formatTimer(seconds) {
  const mins = String(Math.floor(seconds / 60)).padStart(2, "0");
  const secs = String(seconds % 60).padStart(2, "0");
  return `${mins}:${secs}`;
}

export function LiveCallConsole({ tenantId, darkMode }) {
  const [callState, setCallState] = useState("idle");
  const [muted, setMuted] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [audioLevel, setAudioLevel] = useState(0);
  const [errorMsg, setErrorMsg] = useState("");
  const [micDenied, setMicDenied] = useState(false);

  const [transcripts, setTranscripts] = useState([]);
  const [interimText, setInterimText] = useState("");
  const [leadData, setLeadData] = useState({});
  const [highlightedFields, setHighlightedFields] = useState({});
  const [score, setScore] = useState(0);
  const [category, setCategory] = useState("cold");
  const [sentiment, setSentiment] = useState("neutral");
  const [knowledgeSources, setKnowledgeSources] = useState([]);
  const [bookedAppt, setBookedAppt] = useState(null);
  const [showToast, setShowToast] = useState(false);
  const [speakerEnabled, setSpeakerEnabled] = useState(true);

  const wsRef = useRef(null);
  const streamRef = useRef(null);
  const recorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const audioElRef = useRef(null);
  const playbackUrlRef = useRef(null);
  const mediaSourceRef = useRef(null);
  const sourceBufferRef = useRef(null);
  const streamEndedRef = useRef(false);
  const activeTurnRef = useRef(null);
  const mutedRef = useRef(false);
  const prevLeadRef = useRef({});
  const meterRafRef = useRef(0);
  const audioCtxRef = useRef(null);

  useEffect(() => {
    const active = ["listening", "processing", "speaking"].includes(callState);
    if (!active) return;
    const id = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, [callState]);

  useEffect(() => () => cleanupCall(), []);

  function stopPlayback() {
    audioChunksRef.current = [];
    streamEndedRef.current = false;
    sourceBufferRef.current = null;
    if (mediaSourceRef.current) {
      try {
        if (mediaSourceRef.current.readyState === "open") mediaSourceRef.current.endOfStream();
      } catch {
        // ignore
      }
      mediaSourceRef.current = null;
    }
    if (audioElRef.current) {
      audioElRef.current.pause();
      audioElRef.current.removeAttribute("src");
      audioElRef.current.load();
    }
    if (playbackUrlRef.current) {
      URL.revokeObjectURL(playbackUrlRef.current);
      playbackUrlRef.current = null;
    }
  }

  function createSilentAudioUrl() {
    const sampleRate = 8000;
    const sampleCount = sampleRate / 10;
    const buffer = new ArrayBuffer(44 + sampleCount);
    const view = new DataView(buffer);
    const writeText = (offset, text) => {
      for (let i = 0; i < text.length; i += 1) {
        view.setUint8(offset + i, text.charCodeAt(i));
      }
    };

    writeText(0, "RIFF");
    view.setUint32(4, 36 + sampleCount, true);
    writeText(8, "WAVE");
    writeText(12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate, true);
    view.setUint16(32, 1, true);
    view.setUint16(34, 8, true);
    writeText(36, "data");
    view.setUint32(40, sampleCount, true);
    new Uint8Array(buffer, 44).fill(128);
    return URL.createObjectURL(new Blob([buffer], { type: "audio/wav" }));
  }

  function primeAudioPlayback() {
    const audio = new Audio();
    const silentUrl = createSilentAudioUrl();
    audio.muted = true;
    audio.loop = true;
    audio.src = silentUrl;
    audioElRef.current = audio;

    audio.play().then(() => {
      audio.pause();
      audio.currentTime = 0;
      audio.loop = false;
      audio.muted = !speakerEnabled;
      audio.removeAttribute("src");
      audio.load();
      URL.revokeObjectURL(silentUrl);
    }).catch(() => {
      audio.removeAttribute("src");
      audio.load();
      URL.revokeObjectURL(silentUrl);
      setErrorMsg("Audio is blocked by your browser. Use the speaker control to enable playback.");
    });
  }

  function playAudioSource(url) {
    const audio = audioElRef.current || new Audio();
    audioElRef.current = audio;
    if (playbackUrlRef.current) URL.revokeObjectURL(playbackUrlRef.current);
    playbackUrlRef.current = url;
    audio.src = url;
    audio.muted = !speakerEnabled;
    audio.onended = () => {
      URL.revokeObjectURL(url);
      if (playbackUrlRef.current === url) playbackUrlRef.current = null;
    };
    audio.play().catch(() => {
      setErrorMsg("Could not play the agent's voice. Check your browser audio settings and try the speaker control.");
    });
  }

  function decodeBase64(b64) {
    const bin = atob(b64);
    const arr = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i += 1) arr[i] = bin.charCodeAt(i);
    return arr;
  }

  function flushMediaSource() {
    const sb = sourceBufferRef.current;
    const ms = mediaSourceRef.current;
    if (!sb || sb.updating) return;
    if (audioChunksRef.current.length > 0) {
      const next = audioChunksRef.current.shift();
      try {
        sb.appendBuffer(next);
      } catch {
        // ignore aborted buffer
      }
    } else if (streamEndedRef.current && ms && ms.readyState === "open") {
      try {
        ms.endOfStream();
      } catch {
        // ignore
      }
      mediaSourceRef.current = null;
      sourceBufferRef.current = null;
      streamEndedRef.current = false;
    }
  }

  function enqueueAudioChunk(b64, turnId) {
    if (turnId != null && activeTurnRef.current !== turnId) {
      activeTurnRef.current = turnId;
      audioChunksRef.current = [];
      streamEndedRef.current = false;
      sourceBufferRef.current = null;
      mediaSourceRef.current = null;
    }
    const bytes = decodeBase64(b64);
    const canStream = typeof MediaSource !== "undefined" && MediaSource.isTypeSupported("audio/mpeg");
    if (!canStream) {
      audioChunksRef.current.push(bytes);
      return;
    }
    if (!mediaSourceRef.current) {
      streamEndedRef.current = false;
      const ms = new MediaSource();
      mediaSourceRef.current = ms;
      const url = URL.createObjectURL(ms);
      const audio = audioElRef.current || new Audio();
      audioElRef.current = audio;
      if (playbackUrlRef.current) URL.revokeObjectURL(playbackUrlRef.current);
      playbackUrlRef.current = url;
      audio.src = url;
      audio.muted = !speakerEnabled;
      ms.addEventListener("sourceopen", () => {
        if (mediaSourceRef.current !== ms) return;
        try {
          const sb = ms.addSourceBuffer("audio/mpeg");
          sourceBufferRef.current = sb;
          sb.addEventListener("updateend", flushMediaSource);
          flushMediaSource();
          audio.play().catch(() => {
            setErrorMsg("Could not play the agent's voice. Check your browser audio settings and try the speaker control.");
          });
        } catch {
          setErrorMsg("Your browser could not stream the agent's audio format.");
        }
      });
      audio.onended = () => {
        URL.revokeObjectURL(url);
        if (playbackUrlRef.current === url) playbackUrlRef.current = null;
      };
    }
    audioChunksRef.current.push(bytes);
    flushMediaSource();
  }

  function finishAudioStream() {
    const canStream = typeof MediaSource !== "undefined" && MediaSource.isTypeSupported("audio/mpeg");
    if (canStream && mediaSourceRef.current) {
      streamEndedRef.current = true;
      flushMediaSource();
      return;
    }
    if (audioChunksRef.current.length === 0) return;
    const blob = new Blob(audioChunksRef.current, { type: "audio/mpeg" });
    audioChunksRef.current = [];
    const url = URL.createObjectURL(blob);
    playAudioSource(url);
  }

  function startMicMeter(stream) {
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      const ctx = new AudioCtx();
      audioCtxRef.current = ctx;
      const src = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 64;
      src.connect(analyser);
      const data = new Uint8Array(analyser.frequencyBinCount);

      const tick = () => {
        analyser.getByteFrequencyData(data);
        let sum = 0;
        for (let i = 0; i < data.length; i += 1) sum += data[i];
        const norm = mutedRef.current ? 0 : Math.min(1, sum / (data.length * 90));
        setAudioLevel(norm);
        meterRafRef.current = requestAnimationFrame(tick);
      };
      meterRafRef.current = requestAnimationFrame(tick);
    } catch {
      // meter optional
    }
  }

  function cleanupCall() {
    cancelAnimationFrame(meterRafRef.current);
    setAudioLevel(0);
    if (audioCtxRef.current) {
      audioCtxRef.current.close().catch(() => {});
      audioCtxRef.current = null;
    }
    stopPlayback();
    if (recorderRef.current && recorderRef.current.state !== "inactive") {
      recorderRef.current.stop();
    }
    recorderRef.current = null;
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.close();
    }
    wsRef.current = null;
  }

  function highlightNewFields(nextLead) {
    const prev = prevLeadRef.current;
    const changed = {};
    for (const key of Object.keys(nextLead || {})) {
      if (nextLead[key] !== undefined && nextLead[key] !== prev[key]) {
        changed[key] = true;
      }
    }
    prevLeadRef.current = nextLead || {};
    if (Object.keys(changed).length > 0) {
      setHighlightedFields(changed);
      setTimeout(() => setHighlightedFields({}), 1200);
    }
  }

  async function startCall() {
    setErrorMsg("");
    setMicDenied(false);
    mutedRef.current = false;
    setMuted(false);
    setTranscripts([]);
    setInterimText("");
    setLeadData({});
    prevLeadRef.current = {};
    setScore(0);
    setCategory("cold");
    setSentiment("neutral");
    setKnowledgeSources([]);
    setBookedAppt(null);
    setElapsed(0);
    setCallState("connecting");

    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setCallState("error");
      setErrorMsg("This browser does not support microphone calls. Try the latest version of Chrome, Edge, or Firefox.");
      return;
    }

    primeAudioPlayback();

    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      streamRef.current = stream;
      startMicMeter(stream);
    } catch {
      stopPlayback();
      setMicDenied(true);
      setCallState("error");
      setErrorMsg("Microphone permission is required to start a voice call.");
      return;
    }

    let ws;
    try {
      ws = new WebSocket(`${WS_BASE}/ws/call?tenant_id=${tenantId}`);
    } catch {
      cleanupCall();
      setCallState("error");
      setErrorMsg("Unable to connect to the voice service. Check that the backend is running.");
      return;
    }
    wsRef.current = ws;

    ws.onopen = () => {
      try {
        const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
          ? "audio/webm;codecs=opus"
          : "audio/webm";
        const recorder = new MediaRecorder(stream, { mimeType });
        recorderRef.current = recorder;

        recorder.ondataavailable = async (event) => {
          if (event.data.size > 0 && ws.readyState === WebSocket.OPEN && !mutedRef.current) {
            const buf = await event.data.arrayBuffer();
            if (ws.readyState === WebSocket.OPEN) ws.send(buf);
          }
        };
        recorder.start(100);
      } catch {
        cleanupCall();
        setCallState("error");
        setErrorMsg("Could not start microphone recording. Check browser permissions and try again.");
      }
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "call_started") {
          setCallState(msg.state || "listening");
        } else if (msg.type === "state") {
          setCallState(msg.state);
        } else if (msg.type === "transcript") {
          if (msg.role === "user" && !msg.is_final) {
            setInterimText(msg.text);
          } else {
            if (msg.role === "user") setInterimText("");
            setTranscripts((prev) => [...prev, { role: msg.role, text: msg.text }]);
          }
        } else if (msg.type === "lead_update") {
          const nextLead = msg.lead_data || {};
          highlightNewFields(nextLead);
          setLeadData(nextLead);
          setScore(msg.score ?? 0);
          setCategory(msg.category || "cold");
          if (nextLead.interest === "high") setSentiment("interested");
        } else if (msg.type === "knowledge_used") {
          setKnowledgeSources(msg.sources || []);
        } else if (msg.type === "appointment_booked") {
          setBookedAppt(msg.appointment);
          setShowToast(true);
          setTimeout(() => setShowToast(false), 4500);
        } else if (msg.type === "audio_chunk") {
          enqueueAudioChunk(msg.data, msg.turn_id);
        } else if (msg.type === "audio_end") {
          finishAudioStream();
        } else if (msg.type === "stop_audio") {
          stopPlayback();
        } else if (msg.type === "error") {
          setErrorMsg(msg.message || "Voice error");
        }
      } catch {
        setErrorMsg("Received an invalid message from the voice service.");
      }
    };

    ws.onerror = () => {
      setErrorMsg("Connection lost, reconnecting…");
      setCallState("error");
    };

    ws.onclose = () => {
      cleanupCall();
      setCallState((prev) => (prev === "error" ? "error" : "ended"));
    };
  }

  function endCall() {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "end_call" }));
    }
    cleanupCall();
    setCallState("ended");
  }

  function interruptAgent() {
    stopPlayback();
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "interrupt" }));
    }
  }

  function toggleMute() {
    mutedRef.current = !mutedRef.current;
    setMuted(mutedRef.current);
  }

  function toggleSpeaker() {
    const enabled = !speakerEnabled;
    setSpeakerEnabled(enabled);
    if (audioElRef.current) {
      audioElRef.current.muted = !enabled;
      if (enabled && audioElRef.current.src) {
        audioElRef.current.play().catch(() => {
          setErrorMsg("Could not enable audio. Check your browser audio settings and try again.");
        });
      }
    }
  }

  const isActive = ["connecting", "listening", "processing", "speaking"].includes(callState);
  const stageClass = darkMode
    ? "bg-[#05070e] border-white/10 shadow-[0_0_80px_-20px_rgba(59,130,246,0.22)]"
    : "bg-gradient-to-b from-slate-900 to-slate-950 text-white border-slate-800";
  const cardClass = darkMode
    ? "bg-[#0d121f]/85 backdrop-blur-md border-white/10"
    : "bg-white/95 backdrop-blur-md border-slate-200 shadow-sm";

  const leadFields = [
    ["name", "Name", leadData.name],
    ["company", "Company", leadData.company],
    ["budget", "Budget", leadData.budget],
    ["timeline", "Timeline", leadData.timeline],
    ["requirement", "Requirement", leadData.requirement],
    [
      "decision_maker",
      "Decision Maker",
      leadData.decision_maker === true
        ? "Yes"
        : leadData.decision_maker === false
          ? "No"
          : undefined,
    ],
  ];

  return (
    <div className="relative space-y-6">
      {showToast && bookedAppt && (
        <div
          role="status"
          className="fixed top-20 right-6 z-40 flex items-center gap-3 px-4 py-3 rounded-2xl bg-emerald-600/95 backdrop-blur-md text-white shadow-xl"
        >
          <CalendarCheck className="w-5 h-5" />
          <span className="text-sm font-medium">
            Booked for {new Date(bookedAppt.starts_at).toLocaleString()}
          </span>
        </div>
      )}

      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.22em] text-cyan-400">
            <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 shadow-[0_0_12px_rgba(34,211,238,0.8)]" />
            Conversation / Live room
          </div>
          <h1 className="mt-2 text-3xl md:text-4xl font-semibold tracking-tight">Make every first hello count.</h1>
          <p className="mt-2 text-sm text-slate-400">A live conversation, grounded in your knowledge and built for the next step.</p>
        </div>
        <div className="flex items-center gap-2 text-xs text-slate-400">
          <span className="px-3 py-2 rounded-xl border border-white/10 bg-white/[0.03]">
            <span className="text-slate-500">MODE</span><span className="ml-2 text-slate-200">Browser voice</span>
          </span>
          <span className="px-3 py-2 rounded-xl border border-white/10 bg-white/[0.03]">
            <span className="text-slate-500">AGENT</span><span className="ml-2 text-slate-200">On the line</span>
          </span>
        </div>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <section
          className={`lg:col-span-7 relative overflow-hidden rounded-[28px] border p-6 md:p-8 flex flex-col items-center justify-between min-h-[570px] ${stageClass}`}
        >
          <div aria-hidden="true" className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_50%_42%,rgba(49,87,197,0.23),transparent_58%)]" />
          <div aria-hidden="true" className="pointer-events-none absolute inset-0 opacity-[0.14]" style={{ backgroundImage: "radial-gradient(rgba(148,163,184,0.75) 0.7px, transparent 0.7px)", backgroundSize: "24px 24px" }} />

          <div className="relative z-10 w-full flex items-center justify-between text-xs uppercase tracking-[0.18em] text-slate-400">
            <span className="inline-flex items-center gap-2">
              <Sparkles className="w-3.5 h-3.5 text-sky-400" />
              Voice instrument
            </span>
            <span className="font-mono text-sm tracking-normal text-slate-300 px-3 py-1.5 rounded-full bg-white/5 border border-white/10">
              {formatTimer(elapsed)}
            </span>
          </div>

          <div className="relative z-10 my-2 flex flex-col items-center gap-3">
            <VoiceOrb state={callState} audioLevel={audioLevel} />
            <div className="text-center space-y-2">
              <p className="text-xl font-medium tracking-tight text-slate-100" aria-live="polite">
                {STATE_LABELS[callState] || callState}
              </p>
              <p className="text-xs text-slate-400">
                {callState === "idle" || callState === "ended" ? "Your agent is ready when you are." : "Stay present. Your agent is listening."}
              </p>
              {micDenied && (
                <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-rose-500/15 border border-rose-500/30 text-rose-300 text-xs">
                  <AlertTriangle className="w-3.5 h-3.5" />
                  Allow microphone access in your browser to talk.
                </div>
              )}
              {errorMsg && !micDenied && (
                <div role="alert" className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full bg-amber-500/15 border border-amber-500/30 text-amber-300 text-xs">
                  <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                  {errorMsg}
                </div>
              )}
            </div>
          </div>

          <div className="relative z-10 flex items-center gap-3 px-4 py-2.5 rounded-full bg-white/[0.06] backdrop-blur-xl border border-white/10 shadow-lg">
            <button
              type="button"
              aria-label={speakerEnabled ? "Mute agent audio" : "Enable agent audio"}
              aria-pressed={!speakerEnabled}
              onClick={toggleSpeaker}
              className={`p-3 rounded-full border transition duration-150 focus:outline-none focus:ring-2 focus:ring-sky-400 ${
                speakerEnabled
                  ? "bg-white/5 border-white/10 text-slate-200 hover:bg-white/15"
                  : "bg-amber-500/20 border-amber-400/40 text-amber-300"
              }`}
            >
              {speakerEnabled ? <Volume2 className="w-4 h-4" /> : <VolumeX className="w-4 h-4" />}
            </button>
            {!isActive ? (
              <button
                type="button"
                aria-label="Start call"
                onClick={startCall}
                className="inline-flex items-center gap-2.5 px-6 py-2.5 rounded-full font-medium text-sm text-slate-950 bg-white hover:bg-sky-100 focus:outline-none focus:ring-2 focus:ring-sky-400 transition duration-150"
              >
                <Phone className="w-4 h-4" />
                Start call
              </button>
            ) : (
              <>
                <button
                  type="button"
                  aria-label={muted ? "Unmute microphone" : "Mute microphone"}
                  aria-pressed={muted}
                  onClick={toggleMute}
                  className={`p-3 rounded-full border transition duration-150 focus:outline-none focus:ring-2 focus:ring-sky-400 ${
                    muted
                      ? "bg-amber-500/20 border-amber-400/40 text-amber-300"
                      : "bg-white/5 border-white/10 text-slate-200 hover:bg-white/15"
                  }`}
                >
                  {muted ? <MicOff className="w-4 h-4" /> : <Mic className="w-4 h-4" />}
                </button>

                <button
                  type="button"
                  aria-label="Interrupt agent"
                  onClick={interruptAgent}
                  disabled={callState !== "speaking"}
                  className="inline-flex items-center gap-2 px-4 py-2.5 rounded-full bg-white/5 border border-white/10 text-sm text-slate-200 hover:bg-white/15 disabled:opacity-35 transition duration-150 focus:outline-none focus:ring-2 focus:ring-sky-400"
                >
                  <Hand className="w-4 h-4" />
                  Interrupt
                </button>

                <button
                  type="button"
                  aria-label="End call"
                  onClick={endCall}
                  className="p-3 rounded-full bg-rose-500 hover:bg-rose-400 text-white transition duration-150 focus:outline-none focus:ring-2 focus:ring-rose-300"
                >
                  <PhoneOff className="w-4 h-4" />
                </button>
              </>
            )}
          </div>
        </section>

        <section className="lg:col-span-5 flex flex-col gap-5">
        <div className={`rounded-3xl border p-5 flex flex-col h-72 ${cardClass}`}>
          <div className="flex items-center justify-between mb-3 gap-2">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-slate-400">Live Transcript</h2>
            {knowledgeSources.length > 0 && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs bg-sky-500/15 text-sky-300 border border-sky-500/30">
                <BookOpen className="w-3 h-3" />
                {knowledgeSources.join(", ")}
              </span>
            )}
          </div>

          <div className="flex-1 overflow-y-auto space-y-2.5 pr-1" aria-live="polite">
            {transcripts.length === 0 && !interimText && (
              <p className="text-sm text-slate-500">
                Tap Start call and speak naturally — transcripts and lead fields appear here in real time.
              </p>
            )}
            {transcripts.map((item, idx) => (
              <div
                key={idx}
                className={`p-3 rounded-2xl text-sm ${
                  item.role === "assistant"
                    ? "bg-sky-500/10 border border-sky-500/20 mr-6"
                    : "bg-white/5 border border-white/10 ml-6"
                }`}
              >
                <span className="block text-[10px] uppercase tracking-widest text-slate-400 mb-1">
                  {item.role === "assistant" ? "Agent" : "You"}
                </span>
                <span className="font-mono text-[13px] leading-relaxed">{item.text}</span>
              </div>
            ))}
            {interimText && (
              <div className="p-3 rounded-2xl text-sm bg-white/5 border border-dashed border-white/15 ml-6 opacity-65">
                <span className="block text-[10px] uppercase tracking-widest text-slate-400 mb-1">
                  Listening…
                </span>
                <span className="font-mono text-[13px]">{interimText}</span>
              </div>
            )}
          </div>
        </div>

        {bookedAppt && (
          <div className="rounded-2xl border border-emerald-500/30 bg-emerald-500/10 p-4 flex items-center gap-3">
            <CalendarCheck className="w-5 h-5 text-emerald-400 shrink-0" />
            <div className="text-sm">
              <p className="font-semibold text-emerald-300">Appointment Confirmed</p>
              <p className="text-slate-300 font-mono text-xs">
                {new Date(bookedAppt.starts_at).toLocaleString()}
              </p>
            </div>
          </div>
        )}

        <div className={`rounded-3xl border p-5 space-y-4 ${cardClass}`}>
          <ScoreGauge score={score} category={category} sentiment={sentiment} />

          <dl className="grid grid-cols-2 gap-2.5 text-sm">
            {leadFields.map(([key, label, value]) => (
              <div
                key={key}
                className={`p-2.5 rounded-2xl border transition-colors duration-200 ${
                  highlightedFields[key]
                    ? "bg-sky-500/15 border-sky-400/50"
                    : "bg-white/[0.03] border-white/10"
                }`}
              >
                <dt className="text-[10px] uppercase tracking-widest text-slate-400">{label}</dt>
                <dd className="mt-0.5 font-medium truncate">{value || "—"}</dd>
              </div>
            ))}
          </dl>
        </div>
        </section>
      </div>
    </div>
  );
}
