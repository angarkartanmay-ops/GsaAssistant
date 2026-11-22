import * as THREE from "three";

/**
 * HAVOC's core: a procedural "reactor" built only from primitives, generated geometry and a
 * deterministic seed (no downloaded art). Component hierarchy:
 *
 *   core (Group)
 *   ├─ nucleus      icosphere, noise-displaced in the vertex shader, fresnel rim
 *   ├─ lattice      wire icosahedron shell (edges only), slow counter-rotation
 *   ├─ orbits[3]    dashed great circles on tilted planes
 *   ├─ meter        96 instanced ticks on a ring: the audio level meter
 *   └─ dust         seeded point cloud on a thick spherical shell
 *
 * The spec (sizes, counts, speeds) is plain data, separate from the renderer objects.
 */

export type CoreMode = "offline" | "idle" | "listening" | "thinking" | "speaking";

export const CORE_SPEC = {
  seed: 7183,
  accent: new THREE.Color("#5cb4d9"),
  dim: new THREE.Color("#3a3f4a"),
  nucleus: { radius: 1, detail: 48 },
  lattice: { radius: 1.42, detail: 1, opacity: 0.16 },
  orbits: [
    { radius: 1.72, tilt: [0.32, 0, 0.18], dash: 0.09, gap: 0.05, speed: 0.12 },
    { radius: 1.86, tilt: [-0.9, 0.4, 0], dash: 0.02, gap: 0.06, speed: -0.2 },
    { radius: 2.02, tilt: [1.25, -0.2, 0.5], dash: 0.3, gap: 0.12, speed: 0.07 },
  ],
  meter: { count: 96, radius: 2.32, width: 0.018, depth: 0.018, base: 0.05, gain: 0.55 },
  dust: { count: 1400, inner: 2.6, outer: 3.6, size: 0.022 },
  // Per-mode behaviour: rotation speed multiplier, displacement, brightness.
  modes: {
    offline: { speed: 0.15, disp: 0.02, glow: 0.25 },
    idle: { speed: 0.45, disp: 0.05, glow: 0.7 },
    listening: { speed: 0.9, disp: 0.09, glow: 0.95 },
    thinking: { speed: 2.4, disp: 0.07, glow: 0.85 },
    speaking: { speed: 0.8, disp: 0.11, glow: 1 },
  } satisfies Record<CoreMode, { speed: number; disp: number; glow: number }>,
} as const;

/** mulberry32: small deterministic PRNG so the cloud looks identical on every device. */
function rng(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const NUCLEUS_VERT = /* glsl */ `
  uniform float uTime; uniform float uDisp; uniform float uLevel;
  varying vec3 vNormal; varying vec3 vView; varying float vNoise;
  // Cheap smooth 3D noise: layered sines, no texture lookups.
  float n3(vec3 p) {
    return sin(p.x * 2.1 + uTime * 0.9) * sin(p.y * 2.7 - uTime * 0.7) * sin(p.z * 2.3 + uTime * 0.5)
         + 0.5 * sin(p.x * 5.3 - uTime * 1.3) * sin(p.y * 4.9 + uTime * 1.1) * sin(p.z * 5.7);
  }
  void main() {
    float n = n3(position * 1.4);
    vNoise = n;
    vec3 displaced = position + normal * n * (uDisp + uLevel * 0.22);
    vec4 mv = modelViewMatrix * vec4(displaced, 1.0);
    vNormal = normalize(normalMatrix * normal);
    vView = normalize(-mv.xyz);
    gl_Position = projectionMatrix * mv;
  }
`;

const NUCLEUS_FRAG = /* glsl */ `
  uniform vec3 uAccent; uniform vec3 uDeep; uniform float uGlow;
  varying vec3 vNormal; varying vec3 vView; varying float vNoise;
  void main() {
    float fres = pow(1.0 - max(dot(vNormal, vView), 0.0), 2.6);
    float band = smoothstep(0.35, 0.9, vNoise * 0.5 + 0.5);
    vec3 col = mix(uDeep, uAccent * 0.55, band * 0.6);
    col += uAccent * fres * (0.55 + 0.45 * uGlow);
    gl_FragColor = vec4(col, 1.0);
  }
`;

export type CoreModel = {
  group: THREE.Group;
  update: (dt: number, mode: CoreMode, level: number, reducedMotion: boolean) => void;
  dispose: () => void;
};

export function createCoreModel(spec = CORE_SPEC): CoreModel {
  const rand = rng(spec.seed);
  const group = new THREE.Group();
  group.name = "havoc-core";
  const disposables: { dispose(): void }[] = [];
  const track = <T extends { dispose(): void }>(x: T) => (disposables.push(x), x);

  // nucleus
  const nucleusMat = track(
    new THREE.ShaderMaterial({
      vertexShader: NUCLEUS_VERT,
      fragmentShader: NUCLEUS_FRAG,
      uniforms: {
        uTime: { value: 0 },
        uDisp: { value: spec.modes.idle.disp },
        uLevel: { value: 0 },
        uGlow: { value: spec.modes.idle.glow },
        uAccent: { value: spec.accent.clone() },
        uDeep: { value: new THREE.Color("#0e1a22") },
      },
    }),
  );
  const nucleus = new THREE.Mesh(track(new THREE.IcosahedronGeometry(spec.nucleus.radius, spec.nucleus.detail)), nucleusMat);
  nucleus.name = "nucleus";
  group.add(nucleus);

  // lattice
  const latticeGeo = track(new THREE.EdgesGeometry(track(new THREE.IcosahedronGeometry(spec.lattice.radius, spec.lattice.detail))));
  const latticeMat = track(new THREE.LineBasicMaterial({ color: spec.accent, transparent: true, opacity: spec.lattice.opacity }));
  const lattice = new THREE.LineSegments(latticeGeo, latticeMat);
  lattice.name = "lattice";
  group.add(lattice);

  // orbits
  const orbits = spec.orbits.map((o, i) => {
    const pts = new THREE.EllipseCurve(0, 0, o.radius, o.radius, 0, Math.PI * 2).getPoints(256);
    const geo = track(new THREE.BufferGeometry().setFromPoints(pts.map((p) => new THREE.Vector3(p.x, p.y, 0))));
    const mat = track(new THREE.LineDashedMaterial({ color: spec.accent, dashSize: o.dash, gapSize: o.gap, transparent: true, opacity: 0.55 - i * 0.12 }));
    const line = new THREE.Line(geo, mat);
    line.computeLineDistances();
    const pivot = new THREE.Group();
    pivot.rotation.set(o.tilt[0], o.tilt[1], o.tilt[2]);
    pivot.add(line);
    pivot.name = `orbit-${i}`;
    group.add(pivot);
    return { line, speed: o.speed };
  });

  // meter: instanced ticks around a flat ring facing the camera
  const m = spec.meter;
  const tickGeo = track(new THREE.BoxGeometry(m.width, 1, m.depth));
  tickGeo.translate(0, 0.5, 0); // grow outward from the ring
  const tickMat = track(new THREE.MeshBasicMaterial({ color: spec.accent, transparent: true, opacity: 0.8 }));
  const meter = new THREE.InstancedMesh(tickGeo, tickMat, m.count);
  meter.name = "meter";
  const phases = Array.from({ length: m.count }, () => rand() * Math.PI * 2);
  const dummy = new THREE.Object3D();
  group.add(meter);

  // dust
  const d = spec.dust;
  const pos = new Float32Array(d.count * 3);
  for (let i = 0; i < d.count; i++) {
    const u = rand() * 2 - 1;
    const th = rand() * Math.PI * 2;
    const r = d.inner + (d.outer - d.inner) * Math.pow(rand(), 1.6);
    const s = Math.sqrt(1 - u * u);
    pos.set([r * s * Math.cos(th), r * u, r * s * Math.sin(th)], i * 3);
  }
  const dustGeo = track(new THREE.BufferGeometry());
  dustGeo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  const dustMat = track(new THREE.PointsMaterial({ color: spec.accent, size: d.size, transparent: true, opacity: 0.45, sizeAttenuation: true, depthWrite: false }));
  const dust = new THREE.Points(dustGeo, dustMat);
  dust.name = "dust";
  group.add(dust);

  let t = 0;
  let speed: number = spec.modes.idle.speed;
  let smoothLevel = 0;
  const tint = new THREE.Color();

  const update: CoreModel["update"] = (dt, mode, level, reducedMotion) => {
    const target = spec.modes[mode];
    const k = 1 - Math.exp(-dt * 4);
    speed += (target.speed * (reducedMotion ? 0.25 : 1) - speed) * k;
    smoothLevel += (Math.min(1, level) - smoothLevel) * (1 - Math.exp(-dt * 14));
    t += dt * speed;

    const u = nucleusMat.uniforms;
    u.uTime.value = t;
    u.uDisp.value += ((reducedMotion ? 0.02 : target.disp) - u.uDisp.value) * k;
    u.uLevel.value = reducedMotion ? 0 : smoothLevel;
    u.uGlow.value += (target.glow - u.uGlow.value) * k;
    tint.copy(mode === "offline" ? spec.dim : spec.accent);
    (u.uAccent.value as THREE.Color).lerp(tint, k);
    latticeMat.color.lerp(tint, k);
    tickMat.color.lerp(tint, k);
    dustMat.color.lerp(tint, k);

    nucleus.rotation.y = t * 0.35;
    lattice.rotation.set(t * -0.12, t * -0.2, 0);
    orbits.forEach((o) => (o.line.rotation.z = t * o.speed * 3));
    dust.rotation.y = t * 0.05;

    const listening = mode === "listening" || mode === "speaking";
    for (let i = 0; i < m.count; i++) {
      const a = (i / m.count) * Math.PI * 2;
      const wobble = 0.5 + 0.5 * Math.sin(t * 3 + phases[i]);
      const h = m.base + (listening ? smoothLevel * m.gain * (0.35 + 0.65 * wobble) : 0.02 * wobble);
      dummy.position.set(Math.cos(a) * m.radius, Math.sin(a) * m.radius, 0);
      dummy.rotation.set(0, 0, a - Math.PI / 2);
      dummy.scale.set(1, Math.max(0.01, h), 1);
      dummy.updateMatrix();
      meter.setMatrixAt(i, dummy.matrix);
    }
    meter.instanceMatrix.needsUpdate = true;
  };

  return {
    group,
    update,
    dispose: () => {
      disposables.forEach((x) => x.dispose());
      meter.dispose();
    },
  };
}
