import { useEffect, useRef } from "react";

export function VoiceOrb({ state = "idle", audioLevel = 0 }) {
  const canvasRef = useRef(null);
  const stateRef = useRef(state);
  const levelRef = useRef(audioLevel);

  stateRef.current = state;
  levelRef.current = audioLevel;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const size = 340;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = size * dpr;
    canvas.height = size * dpr;
    ctx.scale(dpr, dpr);

    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let rafId = 0;
    let smoothLevel = 0;
    const ripples = [];
    let lastRippleAt = 0;

    function draw(now) {
      const t = now * 0.001;
      const st = stateRef.current;
      const targetLevel = st === "speaking" ? 0.55 + 0.35 * Math.sin(t * 7.5) : levelRef.current;
      smoothLevel += (targetLevel - smoothLevel) * 0.18;

      ctx.clearRect(0, 0, size, size);
      const cx = size / 2;
      const cy = size / 2;
      const baseR = 96;
      const breath = reducedMotion ? 0 : Math.sin(t * 1.6) * 2.5;
      const pulse = st === "speaking" || st === "listening" ? smoothLevel * 10 : 0;
      const r = baseR + breath + pulse;

      // Spawn outward ripples when listening or speaking
      if (!reducedMotion && (st === "listening" || st === "speaking")) {
        const interval = st === "speaking" ? 0.65 : smoothLevel > 0.08 ? 0.55 : 1.3;
        if (t - lastRippleAt > interval) {
          ripples.push({ born: t, strength: Math.max(0.35, smoothLevel) });
          lastRippleAt = t;
        }
      }

      for (let i = ripples.length - 1; i >= 0; i -= 1) {
        const age = t - ripples[i].born;
        const life = 1.8;
        if (age > life) {
          ripples.splice(i, 1);
          continue;
        }
        const prog = age / life;
        const rr = r + prog * 62;
        const alpha = (1 - prog) * 0.42 * ripples[i].strength;
        ctx.beginPath();
        ctx.arc(cx, cy, rr, 0, Math.PI * 2);
        ctx.strokeStyle =
          st === "speaking"
            ? `rgba(125, 211, 252, ${alpha})`
            : `rgba(99, 102, 241, ${alpha})`;
        ctx.lineWidth = 2 * (1 - prog * 0.5);
        ctx.stroke();
      }

      // Soft ambient outer glow
      const glow = ctx.createRadialGradient(cx, cy, r * 0.4, cx, cy, r + 48);
      if (st === "error") {
        glow.addColorStop(0, "rgba(244, 63, 94, 0.35)");
        glow.addColorStop(1, "rgba(244, 63, 94, 0)");
      } else if (st === "speaking") {
        glow.addColorStop(0, "rgba(56, 189, 248, 0.45)");
        glow.addColorStop(1, "rgba(99, 102, 241, 0)");
      } else {
        glow.addColorStop(0, "rgba(96, 165, 250, 0.32)");
        glow.addColorStop(1, "rgba(59, 130, 246, 0)");
      }
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(cx, cy, r + 48, 0, Math.PI * 2);
      ctx.fill();

      // Organic sphere path (subtle wave edge when listening/speaking)
      ctx.save();
      ctx.beginPath();
      const points = 96;
      const edgeAmp =
        reducedMotion
          ? 0
          : st === "speaking"
            ? 4.5 + smoothLevel * 4
            : st === "listening"
              ? 1.5 + smoothLevel * 6
              : st === "processing"
                ? 2.2
                : 0.6;
      const speed = st === "processing" ? 4.5 : st === "speaking" ? 5.5 : 2.2;

      for (let i = 0; i <= points; i += 1) {
        const angle = (i / points) * Math.PI * 2;
        const wobble =
          Math.sin(angle * 3 + t * speed) * edgeAmp * 0.6 +
          Math.cos(angle * 5 - t * (speed * 0.8)) * edgeAmp * 0.4;
        const px = cx + Math.cos(angle) * (r + wobble);
        const py = cy + Math.sin(angle) * (r + wobble);
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      }
      ctx.closePath();
      ctx.clip();

      // Sky-blue & cloud-white fluid sphere base (ChatGPT Voice inspired)
      const angleShift = reducedMotion ? 0 : t * (st === "processing" ? 1.4 : 0.35);
      const gx1 = cx + Math.cos(angleShift) * r * 0.85;
      const gy1 = cy - Math.sin(angleShift) * r * 0.85 - r * 0.2;
      const gx2 = cx - Math.cos(angleShift) * r * 0.85;
      const gy2 = cy + Math.sin(angleShift) * r * 0.85 + r * 0.35;

      const baseGrad = ctx.createLinearGradient(gx1, gy1, gx2, gy2);
      if (st === "error") {
        baseGrad.addColorStop(0, "#fb7185");
        baseGrad.addColorStop(0.55, "#f43f5e");
        baseGrad.addColorStop(1, "#fecdd3");
      } else if (st === "processing") {
        baseGrad.addColorStop(0, "#4f46e5");
        baseGrad.addColorStop(0.5, "#38bdf8");
        baseGrad.addColorStop(1, "#e0f2fe");
      } else {
        baseGrad.addColorStop(0, "#2563eb");
        baseGrad.addColorStop(0.45, "#60a5fa");
        baseGrad.addColorStop(0.75, "#bae6fd");
        baseGrad.addColorStop(1, "#f8fafc");
      }
      ctx.fillStyle = baseGrad;
      ctx.fillRect(cx - r - 20, cy - r - 20, (r + 20) * 2, (r + 20) * 2);

      // Flowing internal cloud / wave ribbons
      const waveCount = 3;
      for (let w = 0; w < waveCount; w += 1) {
        ctx.beginPath();
        const yBase = cy + (w - 1) * 22 + Math.sin(t * 0.9 + w) * 8;
        const amp = (st === "speaking" ? 18 : st === "listening" ? 10 + smoothLevel * 18 : 8) * (1 - w * 0.15);
        const freq = 0.025 + w * 0.008;
        const phase = t * (st === "processing" ? 3.8 : 2.1 + w * 0.5) + w * 2.1;

        ctx.moveTo(cx - r - 15, cy + r + 20);
        for (let x = cx - r - 15; x <= cx + r + 15; x += 4) {
          const y =
            yBase +
            Math.sin(x * freq + phase) * amp +
            Math.cos(x * freq * 1.7 - phase * 0.7) * (amp * 0.45);
          ctx.lineTo(x, y);
        }
        ctx.lineTo(cx + r + 15, cy + r + 20);
        ctx.closePath();

        const waveGrad = ctx.createLinearGradient(cx, yBase - amp, cx, cy + r);
        waveGrad.addColorStop(0, `rgba(255, 255, 255, ${0.32 - w * 0.07})`);
        waveGrad.addColorStop(1, `rgba(186, 230, 253, ${0.12 - w * 0.02})`);
        ctx.fillStyle = waveGrad;
        ctx.fill();
      }

      // Subtle specular top highlight
      const spec = ctx.createRadialGradient(cx - r * 0.3, cy - r * 0.35, 6, cx - r * 0.2, cy - r * 0.25, r * 0.9);
      spec.addColorStop(0, "rgba(255, 255, 255, 0.45)");
      spec.addColorStop(1, "rgba(255, 255, 255, 0)");
      ctx.fillStyle = spec;
      ctx.fillRect(cx - r - 10, cy - r - 10, (r + 10) * 2, (r + 10) * 2);

      ctx.restore();

      if (!reducedMotion) {
        rafId = requestAnimationFrame(draw);
      }
    }

    rafId = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(rafId);
  }, []);

  return (
    <div className="relative flex items-center justify-center w-[300px] h-[300px] sm:w-[340px] sm:h-[340px] select-none" aria-hidden="true">
      <canvas ref={canvasRef} className="w-[340px] h-[340px] max-w-full max-h-full" />
    </div>
  );
}
