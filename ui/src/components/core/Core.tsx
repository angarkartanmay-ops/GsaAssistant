import { memo, useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { createCoreModel, type CoreMode } from "./createCoreModel";

type Props = { mode: CoreMode; level: React.MutableRefObject<number>; className?: string };

/**
 * Isolated WebGL canvas (no Framer Motion inside). Pauses when the tab is hidden,
 * respects prefers-reduced-motion, and falls back to a static SVG when WebGL is unavailable.
 */
function CoreCanvas({ mode, level, className }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const modeRef = useRef(mode);
  const [failed, setFailed] = useState(false);
  modeRef.current = mode;

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "low-power" });
    } catch {
      setFailed(true);
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setClearColor(0x000000, 0);
    el.appendChild(renderer.domElement);
    renderer.domElement.style.width = "100%";
    renderer.domElement.style.height = "100%";

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 50);
    camera.position.set(0, 0, 8.4);
    const model = createCoreModel();
    scene.add(model.group);

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    const resize = () => {
      const { width, height } = el.getBoundingClientRect();
      if (!width || !height) return;
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    };
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    resize();

    // Gentle parallax from the pointer (transform only, no layout work).
    const target = { x: 0, y: 0 };
    const onPointer = (e: PointerEvent) => {
      target.x = (e.clientX / window.innerWidth - 0.5) * 0.35;
      target.y = (e.clientY / window.innerHeight - 0.5) * 0.25;
    };
    window.addEventListener("pointermove", onPointer, { passive: true });

    const clock = new THREE.Clock();
    let raf = 0;
    const loop = () => {
      raf = requestAnimationFrame(loop);
      if (document.hidden) return;
      const dt = Math.min(clock.getDelta(), 0.05);
      model.update(dt, modeRef.current, level.current, reduced.matches);
      model.group.rotation.y += (target.x - model.group.rotation.y) * 0.04;
      model.group.rotation.x += (target.y - model.group.rotation.x) * 0.04;
      renderer.render(scene, camera);
    };
    loop();

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      window.removeEventListener("pointermove", onPointer);
      model.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [level]);

  if (failed) {
    return (
      <div className={className} aria-hidden>
        <svg viewBox="0 0 200 200" className="h-full w-full">
          <circle cx="100" cy="100" r="34" fill="#16303d" stroke="#5cb4d9" strokeOpacity="0.6" />
          <circle cx="100" cy="100" r="62" fill="none" stroke="#5cb4d9" strokeOpacity="0.25" strokeDasharray="6 5" />
          <circle cx="100" cy="100" r="80" fill="none" stroke="#5cb4d9" strokeOpacity="0.15" strokeDasharray="2 6" />
        </svg>
      </div>
    );
  }
  return <div ref={host} className={className} aria-hidden />;
}

export const Core = memo(CoreCanvas);
